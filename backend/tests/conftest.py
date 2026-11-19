import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDER"] = "hash"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
