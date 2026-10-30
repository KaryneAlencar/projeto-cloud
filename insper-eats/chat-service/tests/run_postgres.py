from pathlib import Path
import os
import sys
import unittest
from dotenv import dotenv_values

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    url = os.getenv('CHAT_TEST_DATABASE_URL') or dotenv_values(root / '.env').get('CHAT_DATABASE_URL')
    if not url:
        raise SystemExit('Configure CHAT_TEST_DATABASE_URL ou chat-service/.env')
    os.environ['CHAT_TEST_DATABASE_URL'] = url
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
