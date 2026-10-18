"""运行工作台：配置读取 web.yaml；服务器推荐 Docker Compose。"""

import uvicorn

from rag_tech_retriever.common.config_loader import ConfigLoader

if __name__ == "__main__":
    settings = ConfigLoader.load_default()
    web = ConfigLoader(settings.settings_path.parent / "web.yaml")
    uvicorn.run(
        "rag_tech_retriever.api.main:app",
        host=str(settings.env("WEB_HOST", str(web.get("web.host", "127.0.0.1")))),
        port=int(settings.env("WEB_PORT", str(web.get("web.port", 8766)))),
    )
