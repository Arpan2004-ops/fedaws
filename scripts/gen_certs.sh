#!/usr/bin/env bash
# Generate the self-signed certificate material for the Flower gRPC channel.
#
#     ./scripts/gen_certs.sh                       # local + Cloud Map names
#     ./scripts/gen_certs.sh 54.211.0.10           # also trust a task public IP
#
# Produces certs/ca.crt, certs/ca.key, certs/server.crt, certs/server.key.
# The hospitals pin ca.crt, so a man in the middle cannot present its own
# certificate for the aggregator even though nothing here is publicly trusted.
#
# Run it from the repository root. CERT_DIR must stay a relative path on
# Windows, for the reason explained just below.
set -euo pipefail

# Git Bash on Windows rewrites arguments that look like POSIX paths, which turns
# an OpenSSL subject such as /C=IN/O=... into C:/Program Files/Git/C=IN/O=...
# Disabling that translation is the only way to pass a subject through. It also
# means absolute POSIX paths are no longer translated, so keep CERT_DIR relative.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

EXTRA_SAN="${1:-}"
CERT_DIR="${CERT_DIR:-certs}"
DAYS="${DAYS:-365}"
SUBJECT_BASE="/C=IN/O=FedMed Teaching Federation"

mkdir -p "${CERT_DIR}"

# Subject Alternative Names must cover every address a hospital might dial:
# the compose service name, the Cloud Map record, and localhost for scripts.
SAN="DNS:fl-server,DNS:fl-server.fedmed.local,DNS:localhost,IP:127.0.0.1"
if [[ -n "${EXTRA_SAN}" ]]; then
  if [[ "${EXTRA_SAN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="${SAN},IP:${EXTRA_SAN}"
  else
    SAN="${SAN},DNS:${EXTRA_SAN}"
  fi
fi
echo "Subject Alternative Names: ${SAN}"

echo "1/3 creating the certificate authority"
openssl req -x509 -newkey rsa:4096 -sha256 -days "${DAYS}" -nodes \
  -keyout "${CERT_DIR}/ca.key" -out "${CERT_DIR}/ca.crt" \
  -subj "${SUBJECT_BASE}/CN=FedMed Root CA" 2>/dev/null

echo "2/3 creating the aggregator key and signing request"
openssl req -newkey rsa:4096 -sha256 -nodes \
  -keyout "${CERT_DIR}/server.key" -out "${CERT_DIR}/server.csr" \
  -subj "${SUBJECT_BASE}/CN=fl-server" 2>/dev/null

# The extensions go in a real file rather than a <(process substitution). Native
# Windows OpenSSL cannot open the /dev/fd handle that substitution produces.
EXT_FILE="${CERT_DIR}/openssl-ext.cnf"
cat > "${EXT_FILE}" <<EXT
subjectAltName=${SAN}
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EXT

echo "3/3 signing the aggregator certificate"
openssl x509 -req -in "${CERT_DIR}/server.csr" \
  -CA "${CERT_DIR}/ca.crt" -CAkey "${CERT_DIR}/ca.key" -CAcreateserial \
  -out "${CERT_DIR}/server.crt" -days "${DAYS}" -sha256 \
  -extfile "${EXT_FILE}" 2>/dev/null

rm -f "${CERT_DIR}/server.csr" "${EXT_FILE}"
chmod 600 "${CERT_DIR}"/*.key

echo
echo "Certificates written to ${CERT_DIR}/"
openssl x509 -in "${CERT_DIR}/server.crt" -noout -subject -dates -ext subjectAltName

cat <<'NOTE'

Next steps:
  local   set TLS_ENABLED=true and mount ./certs into the containers at /certs
  aws     ./scripts/upload_certs.sh   (stores them in SSM Parameter Store)

Never commit certs/. The .gitignore in this repo already excludes it.
NOTE
