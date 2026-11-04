"""
tests/test_chatbot.py - Comprehensive Test Suite for Academic AI-1 Project.

Tests all 10 requirements specified in Phase 5:
1. Basic question and answer.
2. Follow-up question.
3. Memory of information mentioned earlier.
4. Multi-turn conversation with at least five turns.
5. Separate conversation IDs (isolation).
6. Context truncation after exceeding the message limit.
7. Empty input rejection.
8. Invalid API key handling.
9. API failure / timeout error handling and rollback.
10. Frontend routes, loading indicators, and error elements.
"""

import os
import sys
import unittest
from dotenv import load_dotenv

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from backend.chatbot import (
    conversations,
    clear_conversation,
    truncate_history,
    get_max_history_messages
)


class TestChatbotApplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv(override=True)
        cls.client = app.test_client()

    def setUp(self):
        # Fresh test session ID for each test
        self.cid = f"test-session-{self._testMethodName}"
        clear_conversation(self.cid)

    def test_01_basic_qa(self):
        """1. Basic question and answer."""
        res = self.client.post("/chat", json={
            "conversation_id": self.cid,
            "message": "What is Python in one sentence?"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("response", data)
        self.assertIn("Python", data["response"])
        print("\n[PASS] Test 1: Basic Q&A succeeded.")

    def test_02_and_03_followup_and_memory(self):
        """2. Follow-up question & 3. Memory of information mentioned earlier."""
        # Turn 1: State name
        r1 = self.client.post("/chat", json={
            "conversation_id": self.cid,
            "message": "My name is Jeevika and I am building an AI chatbot."
        })
        self.assertEqual(r1.status_code, 200)

        # Turn 2: Follow-up asking about prior turn
        r2 = self.client.post("/chat", json={
            "conversation_id": self.cid,
            "message": "What is my name and what am I building?"
        })
        self.assertEqual(r2.status_code, 200)
        reply = r2.get_json()["response"]
        self.assertIn("Jeevika", reply)
        self.assertTrue("chatbot" in reply.lower() or "ai" in reply.lower())
        print("\n[PASS] Test 2 & 3: Follow-up question and memory recall succeeded.")

    def test_04_five_turn_conversation(self):
        """4. Multi-turn conversation with at least five turns."""
        import time
        turns = [
            "Turn 1: I am studying computer science.",
            "Turn 2: What is the primary data structure for LIFO (Last-In, First-Out)?",
            "Turn 3: Can you give a quick Python example of that?",
            "Turn 4: What is the opposite structure (FIFO)?",
            "Turn 5: Summarize the two data structures we just discussed in one sentence."
        ]
        for idx, prompt in enumerate(turns, 1):
            time.sleep(2.0)
            res = self.client.post("/chat", json={
                "conversation_id": self.cid,
                "message": prompt
            })
            self.assertEqual(res.status_code, 200, f"Turn {idx} failed: {res.get_json()}")
            reply = res.get_json()["response"]
            self.assertTrue(len(reply) > 0)
            print(f"  Turn {idx} complete.")

        # Confirm 5 user turns + 5 assistant turns = 10 messages recorded in history
        history = conversations.get(self.cid, [])
        self.assertEqual(len(history), 10)
        print("\n[PASS] Test 4: 5-turn multi-turn conversation verified.")

    def test_05_separate_conversation_ids(self):
        """5. Separate conversation IDs maintain isolated histories."""
        import time
        time.sleep(2.0)
        cid_a = f"{self.cid}-sessionA"
        cid_b = f"{self.cid}-sessionB"

        # Session A shares a secret
        r_a = self.client.post("/chat", json={
            "conversation_id": cid_a,
            "message": "My secret passkey is BLUE-VELVET-42."
        })
        self.assertEqual(r_a.status_code, 200)

        time.sleep(2.0)
        # Session B asks about the secret
        r_b = self.client.post("/chat", json={
            "conversation_id": cid_b,
            "message": "What is my secret passkey?"
        })
        self.assertEqual(r_b.status_code, 200)
        reply_b = r_b.get_json()["response"]
        self.assertNotIn("BLUE-VELVET-42", reply_b)
        print("\n[PASS] Test 5: Conversation session isolation verified.")

    def test_06_context_truncation(self):
        """6. Context truncation after exceeding the message limit."""
        # Create a mock long history of 10 messages
        mock_history = [
            {"role": "user", "content": f"User question {i}"} if i % 2 == 1
            else {"role": "assistant", "content": f"Assistant answer {i}"}
            for i in range(1, 11)
        ]
        # Append latest user turn
        mock_history.append({"role": "user", "content": "Latest user query"})

        truncated = truncate_history(mock_history, max_messages=4)
        # Should retain only up to 4 messages, starting with user turn
        self.assertLessEqual(len(truncated), 4)
        self.assertEqual(truncated[0]["role"], "user")
        self.assertEqual(truncated[-1]["content"], "Latest user query")
        print("\n[PASS] Test 6: Last-N truncation preserves pair integrity and limits window.")

    def test_07_empty_input_validation(self):
        """7. Empty input rejection with 400 status code."""
        # Empty string
        res1 = self.client.post("/chat", json={"conversation_id": self.cid, "message": ""})
        self.assertEqual(res1.status_code, 400)
        self.assertIn("error", res1.get_json())

        # Whitespace-only string
        res2 = self.client.post("/chat", json={"conversation_id": self.cid, "message": "   "})
        self.assertEqual(res2.status_code, 400)
        self.assertIn("error", res2.get_json())

        # Non-JSON payload
        res3 = self.client.post("/chat", data="plain text body")
        self.assertEqual(res3.status_code, 400)
        print("\n[PASS] Test 7: Empty and malformed input validation rejected with 400.")

    def test_08_invalid_api_key(self):
        """8. Invalid API key error handling."""
        res = self.client.post("/chat", json={
            "conversation_id": self.cid,
            "message": "Hello test",
            "api_key_override": "INVALID_API_KEY_12345"
        })
        # Should return 401 Unauthorized or 400 with safe error message
        self.assertIn(res.status_code, (400, 401, 502))
        err_msg = res.get_json()["error"]
        self.assertTrue("API key" in err_msg or "Authentication" in err_msg or "Invalid" in err_msg)
        # Ensure credentials are NOT leaked in message
        self.assertNotIn("INVALID_API_KEY_12345", err_msg)
        print("\n[PASS] Test 8: Invalid API key safely handled without credential leak.")

    def test_09_api_failure_and_rollback(self):
        """9. API failure cleanly rolls back the pending user message."""
        init_history_len = len(conversations.get(self.cid, []))
        # Trigger failure using invalid key
        self.client.post("/chat", json={
            "conversation_id": self.cid,
            "message": "This message should not be persisted on failure",
            "api_key_override": "INVALID_KEY_TRIGGER_FAIL"
        })
        post_history_len = len(conversations.get(self.cid, []))
        # History must NOT retain the unfulfilled turn
        self.assertEqual(init_history_len, post_history_len)
        print("\n[PASS] Test 9: History rollback on failure verified.")

    def test_10_frontend_elements_and_health(self):
        """10. Frontend loading, error states, and health route."""
        # Verify /health route
        h_res = self.client.get("/health")
        self.assertEqual(h_res.status_code, 200)
        h_data = h_res.get_json()
        self.assertEqual(h_data["status"], "ok")

        # Verify frontend index.html DOM structures
        i_res = self.client.get("/")
        self.assertEqual(i_res.status_code, 200)
        html = i_res.data.decode("utf-8")
        self.assertIn('id="typing-indicator"', html)
        self.assertIn('id="error-banner"', html)
        self.assertIn('id="new-chat-btn"', html)
        self.assertIn('id="user-input"', html)
        self.assertIn('id="send-btn"', html)
        print("\n[PASS] Test 10: Frontend elements and health endpoint verified.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
