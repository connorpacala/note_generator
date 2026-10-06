# Clinical note generator

This program drafts a psychiatric medication-management SOAP note from a completed fillable PDF. A local model writes the draft on this computer. The clinician reviews, edits, and signs it.

The model is [Ollama](https://ollama.com/download), listening only at `http://127.0.0.1:11434`. The app refuses any other host, so encounter text is not sent to a cloud model API. Running locally is one safeguard for protected health information. It does not by itself make a clinic HIPAA compliant. Store notes, control access, and handle devices under your own policies.

The default model is text-only, so the PDF is not uploaded. The app reads completed form fields on this machine and puts those answers in the prompt. Blank fields and unchecked boxes are omitted.

## What you need

- Python 3.10 or newer (3.12 is what this project was set up with)
- [Ollama](https://ollama.com/download) for Windows or macOS
- About 8 GB of free disk space for the default model
- A completed copy of the psychiatric medication-management follow-up SOAP form

Memory:

| Machine | Model |
| --- | --- |
| Windows PC with a discrete GPU, or a MacBook Pro with 16 GB or more | `llama3.1:8b` (default) |
| MacBook Pro with 8 GB | `llama3.2:3b` |

On a MacBook Pro with Apple Silicon, Ollama uses the GPU automatically.

## 1. Install Ollama and the model

Install Ollama from https://ollama.com/download and leave it running. On Windows it starts from the system tray. On macOS it stays in the menu bar.

Pull the model once. This download is the model weights, not patient data.

```powershell
ollama pull llama3.1:8b
```

On an 8 GB MacBook Pro, pull the smaller model instead:

```bash
ollama pull llama3.2:3b
```

## 2. Set up Python

From the project directory:

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`requirements.txt` installs `pypdf`, which reads the form. There is no cloud model client.

## 3. Check that the local model is reachable

```powershell
python main.py
```

You should see the model name, `http://127.0.0.1:11434`, and `llama3.1:8b` in the installed list. If Ollama is not running, the command tells you to start it and pull the model.

## 4. Fill the PDF

Open the follow-up form, complete the visit, and save it. The blank template has no answers, and the program will stop rather than invent a note.

Checked boxes and typed text are the only input. A checked negative, such as "No suicidal ideation," is included. An unchecked box is left out.

## 5. Generate a note

Windows:

```powershell
python main.py "C:\path\to\completed-form.pdf"
```

macOS:

```bash
python main.py "/path/to/completed-form.pdf"
```

The draft is printed in the terminal. To also save it:

```powershell
python main.py "C:\path\to\completed-form.pdf" -o note.txt
```

The first note after a restart is slower because Ollama loads the model. Later notes are faster. On a GPU, a note is often ready in well under a minute.

## Choose a different local model

`NOTE_MODEL` overrides the default `llama3.1:8b`. Pull that model with Ollama before you use it.

Windows (PowerShell):

```powershell
$env:NOTE_MODEL = "llama3.2:3b"
python main.py "C:\path\to\completed-form.pdf"
```

macOS:

```bash
export NOTE_MODEL=llama3.2:3b
python main.py "/path/to/completed-form.pdf"
```

`OLLAMA_HOST` defaults to `http://127.0.0.1:11434`. The only accepted hosts are `127.0.0.1`, `localhost`, and `::1`. A remote address is rejected.

## What the draft contains

The note is a SOAP draft: Subjective, Objective, Assessment, and Plan. The model is instructed to use only the completed fields, keep checked safety negatives, and say a section was not documented when nothing was entered for it. Clinician name and signed date appear only when those fields were filled in. The program does not sign the note.

## If something fails

| Message | What to do |
| --- | --- |
| Could not reach Ollama | Install Ollama, start it, and run `ollama pull llama3.1:8b`. |
| Default model is not installed yet | Run `ollama pull` for the model named in the message. |
| PDF not found | Check the path. Quote paths that contain spaces. |
| This PDF has no fillable form fields | Use the fillable SOAP template, not a flattened copy. |
| The PDF has no completed fields | Save the form after filling it. An empty template is rejected. |
| Encrypted PDFs are not supported | Remove the password, or use an unencrypted copy. |
| The model host must be a local address | Leave `OLLAMA_HOST` unset, or set it to `http://127.0.0.1:11434`. |
| The local model returned an empty note | Confirm the model is pulled, then run the command again. |
