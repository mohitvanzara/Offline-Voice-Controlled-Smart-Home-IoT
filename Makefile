
PYTHON      := python3
PIP         := pip3
VENV        := .venv
ACTIVATE    := . $(VENV)/bin/activate

SERVER      := backend/server.py
SPEECH      := speech/speech_recognition.py

.PHONY: help install venv run server speech clean freeze

help:
	@echo ""
	@echo "Available Commands"
	@echo "------------------------------"
	@echo "make install     Install dependencies"
	@echo "make venv        Create Python virtual environment"
	@echo "make run         Run Server + Speech Recognition"
	@echo "make server      Run only Flask server"
	@echo "make speech      Run only Speech Recognition"
	@echo "make clean       Remove cache files"
	@echo "make freeze      Update requirements.txt"
	@echo ""

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@if [ -f backend/requirements.txt ]; then \
		$(PIP) install -r backend/requirements.txt; \
	fi

server:
	$(PYTHON) $(SERVER)

speech:
	$(PYTHON) $(SPEECH)

run:
	@echo "Starting Flask Server..."
	@$(PYTHON) $(SERVER) &
	@sleep 3
	@echo "Starting Speech Recognition..."
	@$(PYTHON) $(SPEECH)

freeze:
	$(PIP) freeze > requirements.txt

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete