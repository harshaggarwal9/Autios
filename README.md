![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-API-green)
![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange)
![Gemini](https://img.shields.io/badge/LLM-Google_Gemini-red)
![MIT License](https://img.shields.io/badge/License-MIT-yellow)

# Autios — An Event-Driven Multi-Agent Industrial Automation System

Autios is an event-driven industrial automation platform that combines Large Language Model (LLM) agents with a Digital Twin to simulate autonomous factory operations. The system orchestrates multiple specialized AI agents that collaborate through shared state and event-driven communication to execute industrial workflows, monitor factory state, and make real-time production decisions.

---

# Overview

Autios models a smart manufacturing environment where autonomous AI agents coordinate factory operations through an event-driven architecture.

The system combines:

- Multi-Agent AI
- Digital Twin
- Event-driven architecture
- FastAPI backend
- Google Gemini reasoning
- Shared Information Model

Instead of directly calling one another, agents communicate through events published to an Event Log and consumed by interested agents using a Subscription Engine.

---

# AI Agents

### Manager Agent

- Receives production tasks
- Creates execution plans
- Delegates work to operator agents
- Coordinates the overall workflow

### Storage Agent

- Retrieves raw materials
- Updates inventory state
- Publishes inventory events

### Inspection Agent

- Performs quality inspection
- Detects production defects
- Reports inspection status

### Painting Agent

- Executes painting operations
- Updates machine status
- Publishes completion events

### Transport Agent

- Simulates robotic transportation
- Moves products between workstations
- Updates Digital Twin location

---

# Key Concepts

- Multi-Agent AI
- Event-Driven Architecture
- Digital Twin
- Shared Information Model
- LangGraph Orchestration
- Google Gemini Integration
- Factory Automation
- Prompt Engineering
- Real-Time Event Processing

---

# Tech Stack

- Python
- FastAPI
- LangGraph
- Google Gemini API
- Pydantic
- SQLAlchemy
- PostgreSQL
- Alembic
- Uvicorn

---

# Architecture

```text
                    User
                      │
                      ▼
                 FastAPI API
                      │
                      ▼
                Manager Agent
                      │
          Creates Production Plan
                      │
                      ▼
                Event Log
                      │
         Subscription Engine
                      │
      ┌───────────────┼────────────────┐
      │               │                │
      ▼               ▼                ▼
 Storage Agent   Inspection Agent  Painting Agent
      │               │                │
      └───────────────┼────────────────┘
                      │
                      ▼
              Transport Agent
                      │
                      ▼
             Command Interface
                      │
                      ▼
             Digital Twin Model
                      │
              Data Observer
                      │
                      ▼
                Rule Engine
                      │
               Generates Events
                      │
                      ▼
                  Event Log
```

---

# Components

### FastAPI Backend

Exposes REST APIs for task creation and simulation control.

### Manager Agent

Uses Google Gemini to create production plans from user requests.

### Operator Agents

Execute specialized industrial tasks while updating the shared Digital Twin.

### Digital Twin

Maintains the current state of machines, workstations, inventory, and products.

### Event Log

Stores semantic events that drive communication between agents.

### Subscription Engine

Routes newly generated events to interested agents.

### Rule Engine

Converts Digital Twin state changes into meaningful factory events.

### Data Observer

Continuously monitors the Digital Twin for state updates.

---

# Project Structure

```text
.
├── agents/
├── api/
├── command/
├── config/
├── core/
├── dataset/
├── db/
├── digital_twin/
├── evaluation/
├── llm/
├── schemas/
├── scripts/
├── tests/
├── alembic/
├── main.py
├── requirements.txt
└── README.md
```

---

# Getting Started

## Prerequisites

- Python 3.10+
- Google Gemini API Key
- PostgreSQL

---

## Installation

```bash
git clone https://github.com/harshaggarwal9/Autios.git

cd Autios

pip install -r requirements.txt
```

---

## Configuration

Linux/macOS

```bash
export GEMINI_API_KEY="your-api-key"
```

Windows PowerShell

```powershell
$env:GEMINI_API_KEY="your-api-key"
```

---

## Run

```bash
uvicorn main:app --reload
```

---

# How It Works

1. A production task is submitted through the FastAPI API.
2. The Manager Agent generates a production plan using Google Gemini.
3. Tasks are published to the Event Log.
4. Operator Agents subscribe to relevant events.
5. Each agent executes its assigned operation.
6. Commands update the Digital Twin.
7. The Data Observer detects state changes.
8. The Rule Engine generates new semantic events.
9. Newly generated events trigger downstream agents.
10. The production workflow completes when all required tasks finish.

---

# Example Workflow

```text
User:
Manufacture Product A

↓

Manager Agent

↓

Production Plan Generated

↓

Storage Agent
Retrieve Materials

↓

Transport Agent
Move Materials

↓

Painting Agent
Paint Component

↓

Inspection Agent
Quality Check

↓

Digital Twin Updated

↓

Production Complete
```

---

# Future Work

- Real PLC integration
- OPC-UA connectivity
- MQTT event streaming
- ROS robot integration
- Reinforcement Learning scheduling
- Kubernetes deployment
- Docker Compose support
- Real factory dashboard
- RAG-enabled manufacturing knowledge base

---

# Notes

- Uses Google Gemini for autonomous planning.
- Event-driven communication reduces coupling between agents.
- Modular architecture enables easy addition of new operator agents.
- Digital Twin provides a single source of truth for factory state.

---

# License

This project is licensed under the **MIT License**.
