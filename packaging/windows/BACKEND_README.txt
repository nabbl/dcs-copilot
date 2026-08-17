MARA standalone backend
=======================

Start on this computer only:
  MaraBackend.exe serve --host 127.0.0.1 --port 47100

Configure the OpenAI key in Windows Credential Manager:
  MaraBackend.exe credentials set-openai

To serve another PC on your LAN, bind explicitly and secure the network first:
  MaraBackend.exe serve --host 0.0.0.0 --port 47100

Binding to 0.0.0.0 exposes MARA to the network. MARA does not create a broad
Windows Firewall rule. Prefer a private network, a narrowly scoped firewall
rule, and HTTPS through a trusted reverse proxy for untrusted networks.

Mutable files are stored below %LOCALAPPDATA%\MARA. Kokoro's model files are
downloaded, SHA-256 verified, and cached automatically on first local backend
startup. OPENAI_API_KEY remains supported for headless deployments;
never put credentials in config.example.json.
