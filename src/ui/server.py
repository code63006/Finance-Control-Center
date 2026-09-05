"""Static dashboard server with a grounded QA endpoint."""
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from src.agent.qa_agent import SettlementQAAgent


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/ask":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            question = str(payload.get("question", "")).strip()
            with open("outputs/qa_state.json", encoding="utf-8") as handle:
                state = json.load(handle)
            response = SettlementQAAgent(state).answer_question(question)
            body = json.dumps({
                "answer": response.answer,
                "confidence": response.confidence,
                "caveats": response.caveats,
                "tool_calls": [
                    {
                        "tool": call.tool_type.value,
                        "result": call.result,
                    }
                    for call in response.tool_calls
                ],
            }, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    port = int(os.environ.get("PORT", "8000"))
    handler = partial(DashboardHandler, directory="outputs")
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Serving dashboard and QA endpoint on http://0.0.0.0:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
