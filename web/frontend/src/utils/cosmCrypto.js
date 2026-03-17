let _Secp256k1 = null;
let _sha256 = null;

export async function ensureCosmCrypto() {
    if (!_Secp256k1 || !_sha256) {
        const mod = await import('@cosmjs/crypto');
        _Secp256k1 = mod.Secp256k1;
        _sha256 = mod.sha256;
    }
    return { Secp256k1: _Secp256k1, sha256: _sha256 };
}
