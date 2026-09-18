src = open("app/main.py", encoding="utf-8").read()
src = src.replace(
    "from fastapi import FastAPI, Request\\nfrom fastapi.responses import JSONResponse",
    "from fastapi import FastAPI, Request\\nfrom fastapi.middleware.cors import CORSMiddleware\\nfrom fastapi.responses import JSONResponse"
)
cors_block = (
    "    # Dev-friendly CORS so the static frontend at :5500 can hit the API at :8000.\\n"
    "    # Production should restrict allow_origins to the real frontend host.\\n"
    "    app.add_middleware(\\n"
    "        CORSMiddleware,\\n"
    "        allow_origins=[\\n"
    "            \\"http://127.0.0.1:5500\\",\\n"
    "            \\"http://localhost:5500\\",\\n"
    "            \\"http://127.0.0.1:8000\\",\\n"
    "            \\"http://localhost:8000\\",\\n"
    "        ],\\n"
    "        allow_credentials=False,\\n"
    "        allow_methods=[\\"GET\\", \\"POST\\", \\"OPTIONS\\"],\\n"
    "        allow_headers=[\\"Content-Type\\"],\\n"
    "        max_age=600,\\n"
    "    )\\n\\n"
    "    @app.exception_handler(GridWiseError)"
)
src = src.replace(
    "    @app.exception_handler(GridWiseError)",
    cors_block
)
open("app/main.py", "w", encoding="utf-8").write(src)
print("ok")
