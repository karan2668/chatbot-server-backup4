import subprocess

subprocess.run("prisma generate", shell=True)

subprocess.run("uvicorn app:app --reload", shell=True)