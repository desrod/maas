/* Copyright 2014 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 */

YUI({ useBrowserConsole: true }).add('maas.shortpoll.tests', function(Y) {

Y.log('loading maas.shortpoll.tests');
var namespace = Y.namespace('maas.shortpoll.tests');

var shortpoll = Y.maas.shortpoll;
var suite = new Y.Test.Suite("maas.shortpoll Tests");

suite.add(new Y.maas.testing.TestCase({
    name: 'test-shortpoll',

    setUp: function() {
        this.constructor.superclass.setUp();
        var old_repoll = shortpoll._repoll;
        shortpoll._repoll = false;
        this.addCleanup(function() {shortpoll._repoll = old_repoll; });
    },

    testInitShortPollManager: function() {
        var manager = new shortpoll.ShortPollManager(
            {uri: '/shortpoll/', eventKey: 'event-key'});
        Y.Assert.areEqual('/shortpoll/', manager.get("uri"));
        Y.Assert.areEqual('event-key', manager.get("eventKey"));
    },

    testInitShortPollManagerDefaults: function() {
        var manager = new shortpoll.ShortPollManager();
        // The default URI is the empty string, i.e. here.
        Y.Assert.areEqual("", manager.get("uri"));
        // The default eventKey is generated by Y.guid() with a custom prefix.
        Y.Assert.areEqual(
            "shortpoll_", manager.get("eventKey").substring(0, 10));
        // The default eventKey is stable.
        Y.Assert.areEqual(manager.get("eventKey"), manager.get("eventKey"));
    },

    testIOAttribute: function() {
        // The IO attribute/property returns the module's `_io` object.
        var manager = new shortpoll.ShortPollManager();
        Y.Assert.areSame(shortpoll._io, manager.get("io"));
        // Changes to the module's `_io` object are reflected immediately.
        var io = shortpoll._io;
        this.addCleanup(function() { shortpoll._io = io; });
        shortpoll._io = Y.guid();
        Y.Assert.areSame(shortpoll._io, manager.get("io"));
    },

    testPollStarted: function() {
        var fired = false;
        Y.on(shortpoll.shortpoll_start_event, function() {
            fired = true;
        });
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        manager.poll();
        Y.Assert.isTrue(fired, "Start event not fired.");
    },

    testPollFailure: function() {
        var fired = false;
        Y.on(shortpoll.shortpoll_fail_event, function() {
            fired = true;
        });
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        // Simulate failure.
        this.mockFailure('unused', shortpoll);
        manager.poll();
        Y.Assert.isTrue(fired, "Failure event not fired.");
    },

    testSuccessPollInvalidData: function() {
        var manager = new shortpoll.ShortPollManager();
        var custom_response = "{{";
        var response = {
            responseText: custom_response
        };
        var res = manager.successPoll("2", response);
        Y.Assert.isFalse(res);
    },

    testSuccessPollMalformedData: function() {
        var manager = new shortpoll.ShortPollManager();
        var response = {
            responseText: '{ 1234: "6" }'
        };
        var res = manager.successPoll("2", response);
        Y.Assert.isFalse(res);
     },

     testSuccessPollWellformedData: function() {
        var manager = new shortpoll.ShortPollManager();
        var response = {
            responseText: '{ "event_key": "4", "something": "6"}'
        };
        var res = manager.successPoll("2", response);
        Y.Assert.isTrue(res);
    },

    testPollDelay: function() {
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        Y.Assert.areEqual(0, manager._failed_attempts);

        var delay = manager.repoll(true);  // Simulate failure.
        Y.Assert.areEqual(shortpoll.SHORT_DELAY, delay);
        Y.Assert.areEqual(1, manager._failed_attempts);

        // While the number of failures is small the delay between polls
        // remains at its initial value, SHORT_DELAY.
        var max_failures = shortpoll.MAX_SHORT_DELAY_FAILED_ATTEMPTS;
        for (; manager._failed_attempts < max_failures - 1;) {
            delay = manager.repoll(true);  // Simulate failure.
            Y.Assert.areEqual(shortpoll.SHORT_DELAY, delay);
        }
        // After MAX_SHORT_DELAY_FAILED_ATTEMPTS failed attempts, the
        // delay changes to LONG_DELAY.
        delay = manager.repoll(true);  // Simulate failure.
        Y.Assert.areEqual(shortpoll.LONG_DELAY, delay);

        // After a success, the delay returns to SHORT_DELAY.
        delay = manager.repoll(false);  // Simulate success.
        Y.Assert.areEqual(shortpoll.SHORT_DELAY, delay);
    },

    testPollURISequence: function() {
        // Each new polling increases the sequence parameter:
        // /shortpoll/?sequence=1
        // /shortpoll/?sequence=2
        // /shortpoll/?sequence=3
        // ...
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        // Simulate success.
        var log = this.mockSuccess('{"i":2}', shortpoll);
        manager.poll();
        var request;
        for (request = 1; request < 10; request++) {
            manager.poll();
            Y.Assert.areEqual(
                '/shortpoll/?sequence=' + (request + 1),
                log.pop()[0]);
        }
    },

    _testDoesNotFail: function(error_code) {
        // Assert that, when the shortpoll request receives an error
        // with code error_code, it is not treated as a failed
        // connection attempt.
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        // Simulate a request timeout.
        this.mockFailure('{"i":2}', shortpoll, error_code);

        Y.Assert.areEqual(0, manager._failed_attempts);
        manager.poll();
        Y.Assert.areEqual(0, manager._failed_attempts);
    },

    test408RequestTimeoutHandling: function() {
        this._testDoesNotFail(408);
    },

    test504GatewayTimeoutHandling: function() {
        this._testDoesNotFail(504);
    },

    testPollPayloadBad: function() {
        // If a non valid response is returned, shortpoll_fail_event
        // is fired.
        var fired = false;
        Y.on(shortpoll.shortpoll_fail_event, function() {
            fired = true;
        });
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        var response = "{non valid json";
        this.mockSuccess(response, shortpoll);
        manager.poll();
        Y.Assert.isTrue(fired, "Failure event not fired.");
    },

    testPollPayloadOk: function() {
        // Create a valid message.
        var custom_response = [
            {'something': {something_else: 1234}},
            {'thisisit': {thatisnot: 5678}}
        ];
        var manager = new shortpoll.ShortPollManager({uri: '/shortpoll/'});
        var event_payload = null;
        Y.on(manager.get("eventKey"), function(data) {
            event_payload = data;
        });
        // Simulate success.
        this.mockSuccess(Y.JSON.stringify(custom_response), shortpoll);
        manager.poll();
        // Note that a utility to compare objects does not yet exist in YUI.
        // http://yuilibrary.com/projects/yui3/ticket/2529868.
        Y.Assert.areEqual(1234, event_payload[0].something.something_else);
        Y.Assert.areEqual(5678, event_payload[1].thisisit.thatisnot);
    },

    testPollURI_appends_sequence_to_existing_query_args: function() {
        // When the URI already contains query arguments, a sequence key is
        // added to the end.
        var manager = new shortpoll.ShortPollManager({uri: 'somewhere?k=v'});
        var log = this.mockSuccess("[]", shortpoll);
        manager.poll();
        Y.Assert.areEqual(1, log.length);
        Y.Assert.areEqual('somewhere?k=v&sequence=1', log[0][0]);
    },

    testPollURI_adds_sequence_as_new_query_arg: function() {
        // When the URI does not already contain query arguments, a sequence
        // key is set as a new query arg.
        var manager = new shortpoll.ShortPollManager({uri: 'somewhere'});
        var log = this.mockSuccess("[]", shortpoll);
        manager.poll();
        Y.Assert.areEqual(1, log.length);
        Y.Assert.areEqual('somewhere?sequence=1', log[0][0]);
    }

}));


namespace.suite = suite;

}, '0.1', {'requires': [
    'node-event-simulate', 'test', 'maas.testing', 'maas.shortpoll']}
);
