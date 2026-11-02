"""Provision text-only corpus fixtures in the owned disposable database, never production."""
import json
import os
import re
import sys
from pathlib import Path

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

run_id = sys.argv[1]
if not re.fullmatch(r'[a-f0-9]{12}', run_id) or os.environ.get('SHILIE_QA_RUN_ID') != run_id:
    raise SystemExit('Owned QA run identity required')
client = PgVectorClient()
if client.host != '127.0.0.1' or client.dbname != 'regression' or client.user != 'regression' or client.port == '5432':
    raise SystemExit('Refusing non-disposable database')
root = Path(__file__).resolve().parents[1]
config = ConfigLoader.load_default()
dimension = int(config.require('embedding.dim'))
table = str(config.require('vector_store.table_name'))
chunks = [json.loads(line) for line in (root / 'data/processed/corpus.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
# These tests exercise SQL/text lookup and stats, not semantic embeddings or recall.
embedding = [1.0] + [0.0] * (dimension - 1)
rows = [{**chunk, 'status_marker': chunk.get('meta', {}).get('status_marker', 'UNKNOWN'), 'embedding': embedding} for chunk in chunks]
try:
    assert client.fetch_scalar('SELECT current_database()') == 'regression'
    client.create_extension()
    client.create_table(table, dimension)
    count = client.upsert_chunks(table, rows, namespace='tech_doc')
    assert client.count(table) == len(chunks)
finally:
    client.close()
print('QA_CORPUS_FIXTURE', count, 'rows; synthetic unit vectors; no semantic-retrieval claim')
