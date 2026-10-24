"""Token safety: the rug-pull / balance-lock vectors a mint carries on chain.

Flags tokens whose deployer can mint more supply, freeze balances, or lock and tax transfers, so the
screener can separate opportunities that are merely visible from ones that are also safe to hold. Both SPL (Tokenkeg) and Token-2022 mints share the 82-byte base layout, so the
authority checks cover both; Token-2022 extensions (transfer hook, non-transferable, transfer fee)
are scanned from the base onward.
"""
from __future__ import annotations

import base64
import struct

import aiohttp

# SPL / Token-2022 Mint base: COption<mint_authority> (36) + supply u64 (8) + decimals u8 +
# is_initialized u8 + COption<freeze_authority> (36). Authority tags are the COption u32 headers.
_MINT_AUTHORITY_TAG = 0
_FREEZE_TAG_OFFSET = 46
_BASE_LEN = 82

# Token-2022 extension types (stable, early in the enum).
_TRANSFER_FEE = 1
_NON_TRANSFERABLE = 9
_TRANSFER_HOOK = 14


async def get_account_data(session: aiohttp.ClientSession, rpc: str, addr: str) -> bytes | None:
    async with session.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                                       "params": [addr, {"encoding": "base64", "commitment": "confirmed"}]}) as r:
        res = await r.json()
    val = (res.get("result") or {}).get("value")
    if not val:
        return None
    return base64.b64decode(val["data"][0])


def _coption_set(data: bytes, offset: int) -> bool:
    return len(data) >= offset + 4 and struct.unpack_from("<I", data, offset)[0] == 1


def mint_authority(data: bytes) -> bool:
    """True when the mint authority is set (the deployer can mint more supply → dump)."""
    return _coption_set(data, _MINT_AUTHORITY_TAG)


def freeze_authority(data: bytes) -> bool:
    """True when the mint has a non-null freeze authority (the dev can freeze token accounts)."""
    return _coption_set(data, _FREEZE_TAG_OFFSET)


# Known token-2022 extension payload sizes (LEN constants). Matching the *exact* size — rather than a
# range — avoids misreading the metadata strings (e.g. a u32 string length of 9 is ``09 00 00 00``,
# which a naive scan mistakes for a NonTransferable extension).
_TRANSFER_HOOK_LEN = 72
_TRANSFER_FEE_LEN = 108
_VALID_TYPES = frozenset(range(1, 20))


def risky_extensions(data: bytes) -> dict:
    """Scan the Token-2022 extension area for balance-locking / taxing extensions.

    Matches a TLV header ``[type: u16][length: u16]`` only when the length equals the known payload
    size for that extension, and (for the zero-length NonTransferable) when the byte after the header
    starts a plausible next extension, so a 9-byte metadata string length is not mistaken for it.
    """
    out = {"transfer_hook": False, "non_transferable": False, "transfer_fee": False}
    n = len(data)
    for off in range(_BASE_LEN, n - 3):
        typ, length = struct.unpack_from("<HH", data, off)
        if typ == _TRANSFER_FEE and length == _TRANSFER_FEE_LEN:
            out["transfer_fee"] = True
        elif typ == _NON_TRANSFERABLE and length == 0:
            # the header must be followed by another extension's type (or the end of data), so a
            # 9-byte metadata string length (``09 00 00 00`` + ASCII) is not mistaken for it.
            nxt = struct.unpack_from("<H", data, off + 4)[0] if off + 6 <= n else 0
            if off + 4 >= n or nxt in _VALID_TYPES:
                out["non_transferable"] = True
        elif typ == _TRANSFER_HOOK and length == _TRANSFER_HOOK_LEN:
            out["transfer_hook"] = True
    return out


_CACHE: dict[str, dict] = {}
_CACHE_MAX = 50_000


def _summarize(mint: str, data: bytes | None) -> dict:
    if data is None:
        return {"mint": mint, "safe": False, "reason": "account not found",
                "freeze": None, "mint_authority": None, "risks": []}
    risks = []
    if freeze_authority(data):
        risks.append("freeze_authority")
    if mint_authority(data):
        risks.append("mint_authority")
    ext = risky_extensions(data)
    if ext["transfer_hook"]:
        risks.append("transfer_hook")
    if ext["non_transferable"]:
        risks.append("non_transferable")
    if ext["transfer_fee"]:
        risks.append("transfer_fee")
    return {"mint": mint, "safe": not risks, "reason": ",".join(risks) if risks else "ok",
            "freeze": "freeze_authority" in risks, "mint_authority": "mint_authority" in risks,
            "risks": risks}


async def check_token(session: aiohttp.ClientSession, rpc: str, mint: str) -> dict:
    """Full token-safety summary. ``safe`` is False on any balance-lock / dump vector, or if unknown.

    Results are cached per mint (the mint/freeze authority never changes for a mint, and hot pools
    recur ~40% of the time), so repeat checks cost one dict hit instead of an RPC round-trip.
    """
    if mint in _CACHE:
        return _CACHE[mint]
    result = _summarize(mint, await get_account_data(session, rpc, mint))
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[mint] = result
    return result


async def check_tokens(session: aiohttp.ClientSession, rpc: str, mints: list[str]) -> dict[str, dict]:
    """Batch ``check_token`` across ``mints`` in one ``getMultipleAccounts`` round-trip (uncached ones)."""
    todo = [m for m in dict.fromkeys(mints) if m not in _CACHE]
    if todo:
        async with session.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                                           "params": [todo, {"encoding": "base64", "commitment": "confirmed"}]}) as r:
            res = await r.json()
        values = (res.get("result") or {}).get("value") or []
        for mint, val in zip(todo, values):
            data = base64.b64decode(val["data"][0]) if val else None
            _CACHE[mint] = _summarize(mint, data)
    return {m: _CACHE.get(m, {"mint": m, "safe": False, "reason": "account not found",
                              "freeze": None, "mint_authority": None, "risks": []}) for m in mints}
