import subprocess

subprocess.run("prisma db push", shell=True)

subprocess.run("uvicorn app:app --reload", shell=True)