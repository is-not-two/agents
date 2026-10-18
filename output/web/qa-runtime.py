from pathlib import Path
import uvicorn
from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.platform.record_store import RecordStore
root=Path(__file__).parent/'qa-runtime-data'
root.mkdir(exist_ok=True)
app=create_app(RecordStore('qa_demo_story_auto'),root,token='')
uvicorn.run(app,host='127.0.0.1',port=8773)
