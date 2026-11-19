"""Recuperação administrativa local de uma conversa antiga, sem transferir proprietários."""
import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect_database
from app.models import Base, BrowserSession, Conversation, ConversationAccess, now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversation', type=UUID, required=True)
    parser.add_argument('--session-reference', required=True)
    args = parser.parse_args()
    engine, sessions = connect_database(Settings.from_env().database_url)
    try:
        with sessions.begin() as session:
            cid = str(args.conversation)
            conversation = session.get(Conversation, cid, with_for_update=True)
            browser = session.get(BrowserSession, args.session_reference)
            if not conversation or not browser or browser.expira_em <= now():
                raise SystemExit('Conversa ou sessão válida não encontrada. Nenhum dado alterado.')
            if session.get(ConversationAccess, cid):
                raise SystemExit('A conversa já possui proprietário. Nenhuma transferência foi feita.')
            session.add(ConversationAccess(conversa_id=cid, sessao_hash=browser.token_hash))
        print('Conversa antiga vinculada à sessão indicada. Histórico e pedidos preservados.')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
