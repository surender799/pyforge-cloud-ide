import argparse


def main():
    p = argparse.ArgumentParser(description="Collaborative Python workspace")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--data", default=".data/pyforge")
    a = p.parse_args()
    import uvicorn
    from .app import create_app

    uvicorn.run(create_app(a.data), host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
