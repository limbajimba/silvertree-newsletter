# Workflow Checkpointing Guide

The newsletter workflow now supports **automatic checkpointing**, which means you can resume from where you left off if interrupted (e.g., with Ctrl+C).

## How It Works

- After each workflow node completes (Initialize, Collect, Triage, Dedupe, etc.), the state is saved to a SQLite database
- If you interrupt the workflow, you can resume from the last completed node
- No need to re-run expensive operations like triage (which makes 757 API calls)

## Usage

### Start a new workflow run
```bash
python -m silvertree_newsletter
```

### Resume from last checkpoint (after Ctrl+C)
```bash
python -m silvertree_newsletter --resume
```

### Use a specific thread ID (for multiple runs)
```bash
# Start a specific run
python -m silvertree_newsletter --thread-id my-custom-run

# Resume that specific run
python -m silvertree_newsletter --thread-id my-custom-run --resume
```

## Example Scenario

1. You start the workflow:
   ```bash
   python -m silvertree_newsletter
   ```

2. It gets to "Triage progress: 50/757" and you hit Ctrl+C

3. Resume from where it left off:
   ```bash
   python -m silvertree_newsletter --resume
   ```

4. The workflow continues from item 51/757, skipping the already-triaged items

## Checkpoint Storage

- Checkpoints are stored in `data/checkpoints/workflow.sqlite`
- Each workflow run has a unique thread ID (auto-generated timestamp by default)
- To clear all checkpoints and start completely fresh, delete the SQLite file:
  ```bash
  rm data/checkpoints/workflow.sqlite
  ```

## Technical Details

This uses [LangGraph's built-in checkpointing](https://docs.langchain.com/oss/python/langgraph/persistence) with SQLite persistence, which saves the complete workflow state after each node execution.

For production use with higher reliability, you can switch to PostgreSQL checkpointing by using `langgraph-checkpoint-postgres` instead.
