Security Model and Limitations
1. Security Overview
This project demonstrates how three smart building controllers can protect their encrypted configuration files by working together.

The controllers are HVAC, Lighting and Access. Each controller has its own encrypted data and signing identity. To decrypt its configuration through the normal protocol, a controller must obtain a valid key share from each of the other two controllers.

This is an educational simulation. All three controllers run as separate services on the same computer.
2. Security Features
| Security mechanism | Purpose |
|---|---|
| AES-256-GCM | Encrypts configuration files and detects changes to the ciphertext |
| Ed25519 | Signs requests and responses so controllers can verify their sender |
| SHA-256 | Compares file hashes with trusted values saved during setup |
| XOR key sharing | Divides each storage key into two shares held by other controllers |
| Nonce and expiration time | Helps prevent reuse of old requests |
| SQLite | Records accepted nonces and security events, including across restarts |

Encryption
Each controller stores its configuration in an encrypted file named storage.enc. AES-256-GCM protects the data. The controller does not store its own complete storage key in its directory.
Digital signatures and integrity
Ed25519 is used to sign protocol messages. Controllers check the signature using the public key saved during setup. They also compare the reported hashes of the manifest and encrypted file with expected values.

A digital signature protects message authenticity, but does not encrypt the message. A file hash check is not proof that a compromised controller is running trusted software.
Replay attack protection
Each signed request contains a random nonce and a short expiration time (up to 30 seconds). A controller records accepted nonces in SQLite. If the same requester sends an already accepted nonce again, the request is rejected.
3. Request Verification
When HVAC requests its key shares, Lighting and Access each check:
1. The requester is a known controller and is not requesting approval from itself.
2. The digital signature is valid.
3. The request is within its allowed time window.
4. The manifest and encrypted-file hashes match the saved values.
5. The requester and nonce combination has not been accepted before.
If the checks pass, the controller records the nonce and returns a signed response containing its key share. HVAC also verifies that both responses come from the correct controllers and match its request.
4. Key Sharing and Decryption
For example, HVAC has two key shares stored elsewhere:
- Lighting holds the first share (S1).
- Access holds the second share (S2).
After receiving both valid shares, HVAC reconstructs the key in memory:

Key = S1 XOR S2

It then uses AES-256-GCM to decrypt its own configuration and returns the result through the API. The service does not save the reconstructed key or the decrypted result to a new file.

If either controller is unavailable or refuses to return a valid share, the normal unlock operation fails.
5. Security Limitations
The system has important limitations:
- All three controllers run on one computer under the same operating-system account. Someone with access to all controller directories could obtain all key shares.
- Controllers communicate over local HTTP (127.0.0.1) without TLS. Share responses are signed but are not encrypted during transmission.
- The local /v1/unlock endpoint does not authenticate a human operator separately.
- A fully compromised controller with its signing key can make false claims, request shares and keep any reconstructed key.
- Both remote controllers must be available for a normal unlock. The system does not support a one-controller failure.
- The local audit database can be changed or deleted, and it does not have unlimited storage management.
For these reasons, this project should be used only as a local educational simulation, not as a production security system.
6. Future Improvements
Possible improvements for a real smart building system include:
- Running controllers on separate physical devices.
- Adding HTTPS or mutual TLS to protect communication.
- Adding operator authentication.
- Supporting key rotation and revocation.
- Improving audit storage and replay-history management.
- Investigating stronger device integrity checks and fault-tolerant key sharing.