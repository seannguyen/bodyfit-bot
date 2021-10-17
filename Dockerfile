# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.9-slim-bullseye

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE 1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED 1
# Add src folder to PYTHONPATH
ENV PYTHONPATH=/app

# Install pip requirements
ADD Pipfile .
ADD Pipfile.lock .
RUN python -m pip install pipenv
RUN python -m pipenv install --deploy --system

WORKDIR /app

# Install chrome and driver
ADD bin/install_chrome.sh ./bin/
RUN apt-get update && apt-get install -y wget curl unzip gnupg2
RUN ./bin/install_chrome.sh

ADD ./*.py ./

# Switching to a non-root user, please refer to https://aka.ms/vscode-docker-python-user-rights
RUN chown -R nobody ./
USER nobody

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
ENTRYPOINT ["python", "bodyfit_bot.py"]
