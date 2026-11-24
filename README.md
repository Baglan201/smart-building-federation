# Federated File System Encoding at the Edge in Smart Buildings Simulation

## Project Description

This project is a Python and FastAPI simulation of secure communication and encrypted data storage in smart buildings. It includes three controllers: **HVAC**, **Lighting**, and **Access**. Each controller runs as a separate service on the same computer.

Each controller stores its configuration in an encrypted file. To decrypt that file through the system, it must request two parts of its encryption key from the other controllers. The system checks digital signatures and other security information before releasing these key shares.

The project demonstrates encryption, authentication, distributed key management, and protection against replay attacks. It is an educational simulation, not a complete physical smart-building system or a mounted file system.

## Main Idea

The main idea is **not to store the complete encryption key together with the encrypted file**. During setup, the key is split into two parts using XOR. Each part is stored on a different controller.

For example, for HVAC:

- **HVAC** stores its encrypted temperature configuration.
- **Lighting** stores the first share of HVAC's encryption key (`S1`).
- **Access** stores the second share (`S2`).

HVAC needs both shares to reconstruct the key:

`Key = S1 XOR S2`

This is a **2-of-2 policy**: both other controllers must provide valid shares for a normal unlock. Lighting and Access follow the same process for their own configurations.

## System Architecture

![HVAC unlock process](docs/architecture.jpg)

[Architecture explanation](docs/ARCHITECTURE.md) | [Editable diagram in Figma / FigJam](https://www.figma.com/board/DUEyVEA1NS2K7VFEM7iB4T)

The diagram shows an example with HVAC. HVAC requests key shares from Lighting and Access, verifies their signed replies, combines the shares, and decrypts its configuration.

| Controller | Role | Local address |
|---|---|---|
| HVAC | Temperature configuration | `127.0.0.1:8101` |
| Lighting | Lighting configuration | `127.0.0.1:8102` |
| Access | Building access configuration | `127.0.0.1:8103` |

Each controller has an encrypted configuration, an Ed25519 signing key, information about trusted peers, key shares for the other controllers, and a local SQLite database for replay protection and security events.

## Tools Used

| Tool / Technology | Purpose |
|---|---|
| Python 3.11+ | Main programming language |
| FastAPI | Provides HTTP endpoints |
| Uvicorn | Runs the local servers |
| Pydantic | Validates requests and responses |
| HTTPX | Sends HTTP requests between controllers |
| Cryptography | Provides encryption and digital signatures |
| AES-256-GCM | Encrypts and authenticates configuration data |
| Ed25519 | Signs and verifies protocol messages |
| SHA-256 | Computes hashes used to detect file changes |
| XOR | Splits and reconstructs encryption keys |
| SQLite | Records used nonces and security events |

## Project Flow

### 1. Initialization

The project begins with an offline setup process called **provisioning**. It creates signing keys, encrypted configuration files, trusted public-key information, and two shares of each encryption key. The shares are stored on the other two controllers.

### 2. Unlock Request

A local operator sends `POST /v1/unlock` to a controller. For example, HVAC prepares a request with its identity, a random nonce, timestamps, and hashes of its files. It signs the request using Ed25519.

### 3. Request Verification

HVAC sends the signed request to Lighting and Access through `POST /v1/share`. Each peer checks the identity, signature, time window, expected hashes, and whether the request nonce was already used. SQLite records accepted nonces to prevent replay attacks.

### 4. Key Share Collection

If the checks pass, each peer returns a signed response containing its share of HVAC's encryption key. HVAC verifies both replies and checks that they belong to the current request.

### 5. Decryption

After receiving both valid shares, HVAC combines them using XOR and decrypts the configuration with AES-256-GCM. The result is returned in the API response.

The service does **not** save an `unlocked.txt` file or write the reconstructed key to disk. If a required controller is unavailable or rejects the request, the normal unlock fails.

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Returns controller status |
| POST | `/v1/share` | Verifies a signed request and returns a signed key share |
| POST | `/v1/unlock` | Collects both shares and decrypts the local configuration |

## Project Structure

```text
smart-building-federation-en/
├── README.md
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md
│   └── architecture.jpg
└── src/
    └── building_federation/
        ├── __init__.py
        ├── __main__.py
        ├── api.py
        ├── cli.py
        ├── crypto.py
        ├── demo.py
        ├── models.py
        ├── provision.py
        ├── service.py
        ├── settings.py
        └── state.py
```

The `.venv/`, `build/`, and `*.egg-info/` directories may appear during installation. They are generated locally and are not part of the source code committed to GitHub.

## How to Run

### 1. Set Up the Environment

The project requires **Python 3.11 or newer**. The following commands use **Python 3.12** on macOS, matching the version used for the local demonstration:

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Run these commands from the main project directory, where `pyproject.toml` is located. If the virtual environment already exists and uses Python 3.12, activate it instead of creating it again.

### 2. Create the Controller Data

```bash
python -m building_federation provision --root runtime
```

This creates a new `runtime/` directory containing data for the three controllers. If `runtime/` already exists, choose another directory name: provisioning does not overwrite existing data.

### 3. Start the Controllers

Open **three terminals**, activate the same virtual environment in each terminal, and run one command per terminal.

**Terminal 1 — HVAC**

```bash
python -m building_federation serve --root runtime --node hvac
```

**Terminal 2 — Lighting**

```bash
python -m building_federation serve --root runtime --node lighting
```

**Terminal 3 — Access**

```bash
python -m building_federation serve --root runtime --node access
```

### 4. Check the System and Unlock HVAC

In a fourth terminal, run:

```bash
curl http://127.0.0.1:8101/health

curl -X POST http://127.0.0.1:8101/v1/unlock \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Example successful response:

```json
{
  "status": "unlocked",
  "node_id": "hvac",
  "approved_by": ["lighting", "access"],
  "data": {
    "controller": "hvac",
    "settings": {
      "zone": "floor-1",
      "target_temperature_c": 22
    }
  }
}
```

You can also open the FastAPI documentation at `http://127.0.0.1:8101/docs` while the HVAC service is running. Stop each server with `Ctrl+C` when finished.

## System Demonstration

The project includes `demo.py`, which automatically creates temporary controller data, starts three local HTTP services, runs **eight scenarios**, and stops the services afterward.

```bash
python -m building_federation.demo
```

| No. | Scenario | Expected result |
|---|---|---|
| 1 | All three controllers request an unlock | Success |
| 2 | A signed request is repeated | Rejected |
| 3 | A repeated request is sent after a controller restarts | Rejected |
| 4 | A request has an invalid digital signature | Rejected |
| 5 | The manifest file is modified | Unlock fails |
| 6 | The encrypted storage file is modified | Unlock fails |
| 7 | One required controller is unavailable | Unlock fails |
| 8 | The unavailable controller returns | Unlock succeeds |

A successful demonstration prints `PASS 01` through `PASS 08`. The demonstration normally uses ports **18101–18103**, while manual startup uses **8101–8103**.

If the demonstration ports are busy, choose another available range:

```bash
python -m building_federation.demo --base-port 19101
```

## Security Features and Limitations

The project uses AES-256-GCM encryption, Ed25519 signatures, SHA-256 hashes, 2-of-2 XOR key sharing, and SQLite replay protection.

There are important limitations:

- All three controllers run on one computer; they are not physically isolated.
- Controllers communicate over local HTTP without TLS encryption.
- The local unlock endpoint does not require a separate operator login.
- The normal unlock process fails if one required controller is unavailable.
- A fully compromised controller or computer can break the security assumptions of this simulation.

This project is intended for **local educational use only**. Do not expose its endpoints to a local network or the Internet. For more detail, see [SECURITY.md](docs/SECURITY.md).

## Future Development Ideas

- Run the controllers on separate physical edge devices.
- Add authenticated HTTPS connections between controllers.
- Add operator authentication and key rotation.
- Improve availability with a different key-sharing approach.
- Create a small dashboard showing controller status and security events.
