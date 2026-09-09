"""CommandOutcome — the three states of a remote command.

See CONTEXT.md -> Remote commands. The point of the type is that "the charger
answered" and "the charger agreed" stopped being the same question.
"""
import pytest
from ocpp.v16 import call_result

from core.connection_manager import CommandOutcome


def _answered(conf):
    return CommandOutcome(True, conf)


class TestAccepted:
    def test_accepted_start_is_accepted(self):
        o = _answered(call_result.RemoteStartTransaction(status="Accepted"))
        assert o.is_accepted
        assert not o.is_refused
        assert not o.is_unanswered
        assert o.status == "Accepted"

    def test_scheduled_counts_as_accepted(self):
        """`Scheduled` is a commitment to act, not a refusal — ChangeAvailability
        only. The one caller that sees it already treats it as an acceptance."""
        o = _answered(call_result.ChangeAvailability(status="Scheduled"))
        assert o.is_accepted
        assert not o.is_refused
        assert o.status == "Scheduled"

    def test_empty_payload_is_accepted(self):
        """OCPP 1.6 UpdateFirmware.conf carries no status at all. There is
        nothing to refuse with, so an answer is an acceptance — reading the
        absence as a refusal would silently break firmware updates."""
        o = _answered(call_result.UpdateFirmware())
        assert o.is_accepted
        assert not o.is_refused
        assert o.status is None


class TestRefused:
    def test_rejected_start_is_refused(self):
        o = _answered(call_result.RemoteStartTransaction(status="Rejected"))
        assert o.is_refused
        assert not o.is_accepted
        assert not o.is_unanswered
        assert o.status == "Rejected"

    def test_rejected_stop_is_refused(self):
        o = _answered(call_result.RemoteStopTransaction(status="Rejected"))
        assert o.is_refused
        assert not o.is_accepted

    @pytest.mark.parametrize("status", ["UnknownMessageId", "UnknownVendorId"])
    def test_non_accepting_datatransfer_statuses_are_refused(self, status):
        """Anything that is not an acceptance is a refusal — the set of
        accepting statuses is the allowlist, not the reject list."""
        o = _answered(call_result.DataTransfer(status=status))
        assert o.is_refused


class TestUnanswered:
    def test_timeout_is_unanswered(self):
        o = CommandOutcome(False, "OCPP timeout: RemoteStartTransaction")
        assert o.is_unanswered
        assert not o.is_accepted
        assert not o.is_refused

    def test_undelivered_is_unanswered(self):
        """Never delivered is still "we do not know what the charger thinks"."""
        o = CommandOutcome(False, "Charge point CP1 not connected")
        assert o.is_unanswered
        assert not o.is_refused

    def test_unanswered_has_no_status(self):
        assert CommandOutcome(False, "OCPP timeout: Reset").status is None

    def test_unanswered_is_distinguishable_without_string_sniffing(self):
        """The admin endpoint currently sniffs for an "OCPP timeout" prefix to
        decide 504 vs 500. Callers must not need that."""
        timeout = CommandOutcome(False, "OCPP timeout: RemoteStartTransaction")
        refused = _answered(call_result.RemoteStartTransaction(status="Rejected"))
        assert timeout.is_unanswered and not refused.is_unanswered


class TestTheTupleShapeIsGone:
    """Issue 04 is the contract half. `TestBackwardCompatibility` lived here and
    is deliberately deleted, not ported — its three tests asserted that
    `success, response = outcome` kept working, which was true only while call
    sites were migrating one command at a time.

    Where each intent went:

    * `test_unpacks_as_the_historical_pair` — inverted below. Unpacking is now
      an error, and that is the guarantee worth holding.
    * `test_answered_is_true_even_when_refused` — the *distinction* it protected
      is covered by `TestRefusal`; what it actually asserted (a refusal reads as
      the historical `True`) is the exact conflation issue 04 exists to remove.
    * `test_answered_is_false_when_undelivered` — survives as
      `.answered is False` / `.is_unanswered`, covered above.
    """

    def test_unpacking_an_outcome_raises(self):
        """The boolean pair is what made "answered" and "agreed" look alike.
        Failing loudly beats any caller quietly reintroducing it."""
        outcome = _answered(call_result.RemoteStartTransaction(status="Rejected"))
        with pytest.raises(TypeError):
            _success, _response = outcome  # noqa: F841

    def test_the_fields_are_still_reachable_by_name(self):
        conf = call_result.RemoteStartTransaction(status="Accepted")
        outcome = CommandOutcome(True, conf)
        assert outcome.answered is True
        assert outcome.response is conf

    def test_an_undelivered_command_is_unanswered_not_refused(self):
        outcome = CommandOutcome(False, "not connected")
        assert outcome.answered is False
        assert outcome.is_unanswered and not outcome.is_refused
        assert outcome.response == "not connected"
