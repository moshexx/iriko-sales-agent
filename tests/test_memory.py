"""
Integration tests for conversation memory (app/services/memory.py).

Uses a REAL Postgres container (via testcontainers in conftest.py).
Why real DB here?
  - load_history uses ORDER BY + LIMIT — must test real SQL semantics.
  - save_turn uses flush() inside a transaction — must test real commit behavior.
  - With mocks we'd just test our mock, not the actual query.

Each test gets a fresh transaction (rolled back after) so tests don't interfere.

Key test cases:
  1. Empty history for new chat — returns []
  2. save_turn persists two messages (user + assistant)
  3. load_history returns messages in chronological order (oldest first)
  4. load_history respects the limit parameter
  5. load_history is isolated by tenant_id (no cross-tenant leakage)
  6. load_history is isolated by chat_id (different chats don't mix)
  7. get_message_count returns correct count
"""

import uuid

import pytest

from app.services.memory import get_message_count, load_history, save_turn

# ─── Fixtures ─────────────────────────────────────────────────────────────────

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
CHAT_1 = "972501111111@c.us"
CHAT_2 = "972502222222@c.us"


@pytest.fixture(autouse=True)
def ensure_message_model_registered():
    """Ensure Message model is imported so its table is created by db_engine."""
    import app.models.message  # noqa: F401


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestLoadHistory:
    async def test_empty_history_for_new_chat(self, db_session, make_tenant):
        """A brand-new chat has no history — must return []."""
        await make_tenant(instance_id="9991001", slug="tenant-mem-1")
        history = await load_history(TENANT_A, CHAT_1, db_session)
        assert history == []

    async def test_load_history_returns_messages_after_save(self, db_session, make_tenant):
        """After save_turn, load_history must return both messages."""
        await make_tenant(instance_id="9991002", slug="tenant-mem-2")

        await save_turn(
            tenant_id=TENANT_A,
            chat_id=CHAT_1,
            user_text="שלום, אני מעוניין בהשתלת שיער",
            assistant_text="ברוך הבא! נשמח לעזור. כמה שנים אתה סובל מנשירת שיער?",
            db=db_session,
        )

        history = await load_history(TENANT_A, CHAT_1, db_session)

        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "שלום, אני מעוניין בהשתלת שיער"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "ברוך הבא! נשמח לעזור. כמה שנים אתה סובל מנשירת שיער?"

    async def test_history_is_chronological_oldest_first(self, db_session, make_tenant):
        """
        Two turns: turn 1 then turn 2.
        load_history must return: user1, assistant1, user2, assistant2.
        (oldest first — correct order for LLM prompt construction)
        """
        await make_tenant(instance_id="9991003", slug="tenant-mem-3")

        await save_turn(TENANT_A, CHAT_1, "שאלה ראשונה", "תשובה ראשונה", db_session)
        await save_turn(TENANT_A, CHAT_1, "שאלה שנייה", "תשובה שנייה", db_session)

        history = await load_history(TENANT_A, CHAT_1, db_session)

        assert len(history) == 4
        assert history[0]["content"] == "שאלה ראשונה"   # oldest first
        assert history[1]["content"] == "תשובה ראשונה"
        assert history[2]["content"] == "שאלה שנייה"
        assert history[3]["content"] == "תשובה שנייה"   # most recent last

    async def test_load_history_respects_limit(self, db_session, make_tenant):
        """
        If limit=2 is passed, only the 2 most recent messages are returned.
        (Simulates a context window constraint.)
        """
        await make_tenant(instance_id="9991004", slug="tenant-mem-4")

        await save_turn(TENANT_A, CHAT_1, "turn 1 user", "turn 1 assistant", db_session)
        await save_turn(TENANT_A, CHAT_1, "turn 2 user", "turn 2 assistant", db_session)
        await save_turn(TENANT_A, CHAT_1, "turn 3 user", "turn 3 assistant", db_session)

        history = await load_history(TENANT_A, CHAT_1, db_session, limit=2)

        # Should return the 2 MOST RECENT messages (the last turn), oldest-first
        assert len(history) == 2
        assert history[0]["content"] == "turn 3 user"
        assert history[1]["content"] == "turn 3 assistant"

    async def test_history_role_structure(self, db_session, make_tenant):
        """Each message dict must have exactly 'role' and 'content' keys."""
        await make_tenant(instance_id="9991005", slug="tenant-mem-5")
        await save_turn(TENANT_A, CHAT_1, "hello", "hi there", db_session)

        history = await load_history(TENANT_A, CHAT_1, db_session)

        for msg in history:
            assert set(msg.keys()) == {"role", "content"}
            assert msg["role"] in ("user", "assistant")


class TestTenantIsolation:
    async def test_different_tenants_have_separate_histories(self, db_session, make_tenant):
        """
        CRITICAL: Tenant A's chat history must NOT appear in Tenant B's history.
        This is the core multi-tenancy isolation test for memory.
        """
        await make_tenant(instance_id="9991010", slug="tenant-iso-a")
        await make_tenant(instance_id="9991011", slug="tenant-iso-b")

        # Tenant A sends a message
        await save_turn(TENANT_A, CHAT_1, "tenant A message", "tenant A reply", db_session)

        # Tenant B loads the same chat_id — must get empty history
        history_b = await load_history(TENANT_B, CHAT_1, db_session)
        assert history_b == []

    async def test_different_chats_have_separate_histories(self, db_session, make_tenant):
        """
        Chat 1 and Chat 2 within the same tenant must have separate histories.
        """
        await make_tenant(instance_id="9991012", slug="tenant-chat-iso")

        await save_turn(TENANT_A, CHAT_1, "chat 1 message", "chat 1 reply", db_session)
        await save_turn(TENANT_A, CHAT_2, "chat 2 message", "chat 2 reply", db_session)

        history_1 = await load_history(TENANT_A, CHAT_1, db_session)
        history_2 = await load_history(TENANT_A, CHAT_2, db_session)

        assert len(history_1) == 2
        assert len(history_2) == 2
        assert history_1[0]["content"] == "chat 1 message"
        assert history_2[0]["content"] == "chat 2 message"


class TestSaveTurn:
    async def test_saves_user_and_assistant_message(self, db_session, make_tenant):
        """save_turn must persist exactly 2 messages (user + assistant)."""
        await make_tenant(instance_id="9991020", slug="tenant-save-1")

        count_before = await get_message_count(TENANT_A, CHAT_1, db_session)
        await save_turn(TENANT_A, CHAT_1, "user msg", "assistant msg", db_session)
        count_after = await get_message_count(TENANT_A, CHAT_1, db_session)

        assert count_after - count_before == 2

    async def test_saves_id_message_on_user_message(self, db_session, make_tenant):
        """id_message from Green API should be stored on the user message row."""
        await make_tenant(instance_id="9991021", slug="tenant-save-2")

        await save_turn(
            TENANT_A, CHAT_1, "user msg", "assistant msg", db_session,
            id_message="greenapi-msg-abc123",
        )

        from sqlalchemy import select

        from app.models.message import Message

        result = await db_session.execute(
            select(Message)
            .where(
                Message.tenant_id == uuid.UUID(TENANT_A),
                Message.chat_id == CHAT_1,
                Message.role == "user",
            )
        )
        user_msg = result.scalar_one()
        assert user_msg.id_message == "greenapi-msg-abc123"

    async def test_multiple_turns_accumulate(self, db_session, make_tenant):
        """Each save_turn call adds 2 rows — 3 turns = 6 rows."""
        await make_tenant(instance_id="9991022", slug="tenant-save-3")

        for i in range(3):
            await save_turn(TENANT_A, CHAT_1, f"user {i}", f"assistant {i}", db_session)

        count = await get_message_count(TENANT_A, CHAT_1, db_session)
        assert count == 6


class TestGetMessageCount:
    async def test_count_zero_for_empty_chat(self, db_session, make_tenant):
        await make_tenant(instance_id="9991030", slug="tenant-count-1")
        count = await get_message_count(TENANT_A, CHAT_1, db_session)
        assert count == 0

    async def test_count_increments_per_turn(self, db_session, make_tenant):
        await make_tenant(instance_id="9991031", slug="tenant-count-2")
        await save_turn(TENANT_A, CHAT_1, "u", "a", db_session)
        assert await get_message_count(TENANT_A, CHAT_1, db_session) == 2
        await save_turn(TENANT_A, CHAT_1, "u2", "a2", db_session)
        assert await get_message_count(TENANT_A, CHAT_1, db_session) == 4
