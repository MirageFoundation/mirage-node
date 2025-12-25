import { HDKey } from '@scure/bip32';
import { getPublicKey as secp256k1GetPublicKey } from '@noble/secp256k1';
import { mnemonicToSeedSync } from 'bip39';
import { bech32 } from 'bech32';
import CryptoJS from 'crypto-js';

const bytesToHex = (bytes) => Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');

const pubkeyHexToMirageAddress = (pubkeyHex) => {
    const sha = CryptoJS.SHA256(CryptoJS.enc.Hex.parse(pubkeyHex));
    const rip = CryptoJS.RIPEMD160(sha);
    const addrHex = rip.toString(CryptoJS.enc.Hex);
    const addrBytes = Uint8Array.from(addrHex.match(/.{1,2}/g).map((b) => parseInt(b, 16)));
    const words = bech32.toWords(addrBytes);
    return bech32.encode('mirage', words);
};

// Derive private key from seed phrase using Cosmos BIP44 path m/44'/118'/0'/0/0
export const derivePrivateKeyFromSeed = (seedPhrase) => {
    const seed = mnemonicToSeedSync(seedPhrase, "");
    const hd = HDKey.fromMasterSeed(seed);
    const child = hd.derive("m/44'/118'/0'/0/0");
    const privBytes = child.privateKey;
    if (!privBytes) {
        throw new Error("Failed to derive private key from seed phrase");
    }
    return bytesToHex(privBytes);
};

// Derive public key and address from seed phrase
export const derivePublicKeyFromSeed = (seedPhrase) => {
    const seed = mnemonicToSeedSync(seedPhrase, "");
    const hd = HDKey.fromMasterSeed(seed);
    const child = hd.derive("m/44'/118'/0'/0/0");
    const privBytes = child.privateKey;
    if (!privBytes) {
        throw new Error("Failed to derive keys from seed phrase");
    }
    const pubBytes = secp256k1GetPublicKey(privBytes, true);
    const pubHex = bytesToHex(pubBytes);
    const address = pubkeyHexToMirageAddress(pubHex);
    return address;
};

// Get both private key and address from seed phrase
export const deriveKeysFromSeed = (seedPhrase) => {
    const seed = mnemonicToSeedSync(seedPhrase, "");
    const hd = HDKey.fromMasterSeed(seed);
    const child = hd.derive("m/44'/118'/0'/0/0");
    const privBytes = child.privateKey;
    if (!privBytes) {
        throw new Error("Failed to derive keys from seed phrase");
    }
    const privateKey = bytesToHex(privBytes);
    const pubBytes = secp256k1GetPublicKey(privBytes, true);
    const pubHex = bytesToHex(pubBytes);
    const publicKey = pubkeyHexToMirageAddress(pubHex);
    return { privateKey, publicKey };
};
