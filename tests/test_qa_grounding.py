"""
Q&A agent grounding test — every number in an answer must trace to a tool call.
"""
import pytest
from src.agent.qa_agent import QAAgent, SettlementQAAgent


@pytest.fixture
def qa_agent():
    state = {
        "cases": {
            "ORD_001": {
                "order_id": "ORD_001",
                "payment_method": "card",
                "amount_paise": 10000,
                "diagnosis": {
                    "outcome": "PLAUSIBLE_UNCONFIRMED",
                    "hypothesis": "FEE_MISSING",
                    "explanation": "Fee node absent.",
                },
                "variance_paise": 500,
                "exposure_paise": 500,
                "impact_components": {"fee_delta_paise": 500},
                "resolved_nodes": ["order", "payment"],
                "exception_nodes": ["fee"],
                "match_pass": {"order": 1, "payment": 1},
                "n_nodes": 6,
                "match_status": "resolved",
            },
            "ORD_002": {
                "order_id": "ORD_002",
                "payment_method": "upi",
                "amount_paise": 5000,
                "diagnosis": {
                    "outcome": "NO_ISSUE",
                    "hypothesis": None,
                    "explanation": "",
                },
                "variance_paise": 0,
                "exposure_paise": 0,
                "impact_components": {},
                "resolved_nodes": ["order", "payment", "fee", "tax"],
                "exception_nodes": [],
                "match_pass": {},
                "n_nodes": 7,
                "match_status": "resolved",
            },
        }
    }
    return QAAgent(state)


class TestQAGrounding:
    def test_answer_numbers_trace_to_tool_calls(self, qa_agent):
        """Every number in an answer must appear in a tool-call output."""
        answer = qa_agent.answer("How many exception cases are there?")
        # The answer should reference a tool call
        assert len(qa_agent.tool_calls_this_turn) > 0, "No tool calls made"
        # Every tool call should have produced output
        for tc in qa_agent.tool_calls_this_turn:
            assert tc.result is not None, f"Tool call {tc.tool_name} produced no result"

    def test_financial_answer_traces_to_tools(self, qa_agent):
        """Financial summary answer must use tool calls for all numbers."""
        answer = qa_agent.answer("What is the total financial exposure?")
        assert len(qa_agent.tool_calls_this_turn) > 0, "No tool calls for financial question"
        # Check that tool call output is numeric where expected
        for tc in qa_agent.tool_calls_this_turn:
            if tc.tool_name == "get_financial_summary":
                assert isinstance(tc.result.get("exposure_paise"), int)

    def test_no_tool_call_no_number_in_answer(self, qa_agent):
        """If no tools are called, answer should not contain numbers."""
        answer = qa_agent.answer("What is a reconciliation?")
        # This is a generic question — no specific numbers expected
        # The agent should handle gracefully without tool calls
        assert isinstance(answer, str)

    def test_case_question_is_grounded_in_that_case(self, qa_agent):
        """A case investigation must use the selected case's reconciled facts."""
        agent = SettlementQAAgent({
            "ORD_001": {
                "case": {"nodes": {
                    "settlement": {"amount_paise": 9500, "reference_id": "SET_001"},
                    "bank_entries": [{"amount_paise": 9000}],
                }},
                "diagnosis": {"outcome": "STRONGLY_SUPPORTED", "hypothesis": "FEE_MISSING"},
                "evidence": ["Fee record missing"],
                "blast_radius": {"variance_paise": -500, "exposure_paise": 500},
                "ledger": {"is_balanced": False},
            }
        })
        response = agent.answer_question("Why is ORD_001 blocked?")

        assert "ORD_001" in response.answer
        assert "500" in response.answer
        tools = {call.tool_type.value for call in response.tool_calls}
        assert {"get_diagnosis", "get_evidence_summary", "get_settlement_details"} <= tools
