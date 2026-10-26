"""Admin commands for API keys.

    python -m backend.manage create-key "My website"   create a key (shown only once!)
    python -m backend.manage list-keys                  show all keys (never the keys themselves)
    python -m backend.manage revoke-key 3               switch key number 3 off
    python -m backend.manage memory                     what Jarvis remembers (saved answers, voice chats)
    python -m backend.manage clear-answers              forget all saved answers
"""
import sys

from backend import migrate
from backend.database import connect
from backend.repositories import AnswerCacheRepository, ApiKeyRepository, ConversationRepository, MessageRepository
from backend.services.auth_service import AuthService
from backend.services.desktop_memory import DESKTOP_OWNER


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    command, args = sys.argv[1], sys.argv[2:]
    db = connect()
    try:
        if migrate.pending(db):
            sys.exit("Run `python -m backend.migrate up` first.")
        keys = ApiKeyRepository(db)
        if command == "create-key" and args:
            key_id, key = AuthService(keys).create_key(" ".join(args))
            print(f"API key {key_id} created. Copy it now, it won't be shown again:\n\n    {key}\n")
        elif command == "list-keys":
            for row in keys.list_all():
                state = f"revoked {row['revoked_at']}" if row["revoked_at"] else "active"
                print(f"{row['id']:>3}  {row['name']:<30} created {row['created_at']}  {state}")
        elif command == "memory":
            answers = AnswerCacheRepository(db)
            print(f"Saved answers: {answers.count()} (most used first)")
            for row in answers.most_used(15):
                print(f"  {row['hits']:>3} reuses  {row['question'][:70]}")
            desktop = keys.find_active_by_name(DESKTOP_OWNER)
            if desktop:
                conv = ConversationRepository(db).list_for_owner(desktop["id"], limit=1, offset=0)
                if conv:
                    print(f"\nVoice chats saved: {conv[0]['message_count']} messages. Latest:")
                    for m in MessageRepository(db).latest(conv[0]["id"], 6):
                        print(f"  {'You' if m['role'] == 'user' else 'Jarvis'}: {m['content'][:90]}")
        elif command == "clear-answers":
            with db:
                print(f"Forgot {AnswerCacheRepository(db).clear()} saved answers.")
        elif command == "revoke-key" and args and args[0].isdigit():
            with db:
                done = keys.revoke(int(args[0]))
            print("Revoked." if done else "No active key with that id.")
        else:
            print(__doc__)
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
