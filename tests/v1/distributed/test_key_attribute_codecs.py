# SPDX-License-Identifier: Apache-2.0
"""Recovery and backend key naming preserve extensible opaque_identity."""

# Standard
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

# Third Party
import pytest

# First Party
from lmcache.v1.distributed.api import ObjectKey
from lmcache.v1.distributed.l2_adapters.bigtable_key_encoder import BigtableL2KeyEncoder
from lmcache.v1.distributed.l2_adapters.fs_l2_adapter import (
    _filename_to_object_key,
    _object_key_to_filename,
)
from lmcache.v1.distributed.l2_adapters.native_connector_l2_adapter import (
    _object_key_to_string,
)
from lmcache.v1.distributed.l2_adapters.s3_l2_adapter import (
    _object_key_to_string as s3_name,
)
from lmcache.v1.distributed.l2_adapters.s3_l2_adapter import (
    _string_to_object_key,
)
from lmcache.v1.distributed.serde.utils import make_temp_key
from lmcache.v1.key_attributes import KeyAttribute, encode_matching_attributes
from lmcache.v1.mp_observability.trace.codecs import decode_value, encode_value


@pytest.mark.parametrize("salt", ["", "tenant"])
def test_backend_names_recovery_and_trace(salt: str) -> None:
    key = ObjectKey(
        b"1234",
        "org/model",
        1,
        cache_salt=salt,
        opaque_identity=(KeyAttribute("dtype", "bf16"),),
        metadata=(KeyAttribute("trace", "a"),),
        identity_metadata=(KeyAttribute("codec", "raw-v1"),),
    )
    hint = replace(key, metadata=(KeyAttribute("trace", "b"),))
    other = replace(key, opaque_identity=(KeyAttribute("dtype", "fp8"),))
    for encode in (
        _object_key_to_filename,
        _object_key_to_string,
        s3_name,
        BigtableL2KeyEncoder().encode_row_key,
        BigtableL2KeyEncoder("{model}@{hash}").encode_row_key,
    ):
        assert encode(key) == encode(hint)
        assert encode(key) != encode(other)
    for recovered in (
        _filename_to_object_key(_object_key_to_filename(key)),
        _string_to_object_key(s3_name(key)),
    ):
        assert recovered == key
        assert recovered.metadata == ()
        assert recovered.identity_metadata == key.identity_metadata
    temp = make_temp_key(key)
    assert temp.metadata == key.metadata
    assert temp.identity_metadata == key.identity_metadata
    assert temp.chunk_hash != key.chunk_hash
    traced = decode_value(encode_value(key))
    assert traced == key
    assert traced.metadata == key.metadata


def test_fs_rejects_invalid_or_overlong_extension() -> None:
    key = ObjectKey(
        b"1234", "model", 1, opaque_identity=(KeyAttribute("large", "a" * 200),)
    )
    with pytest.raises(ValueError, match="NAME_MAX"):
        _object_key_to_filename(key)
    assert _filename_to_object_key("model@0x00000001@0@31323334@@x2-abc.data") is None


def test_cpp_codec_matches_python(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler required for native key-codec parity")
        return
    root = Path(__file__).resolve().parents[3]
    source = tmp_path / "key-codec.cpp"
    source.write_text("""
#include <iostream>
#include "csrc/storage_backends/keys.h"
int main(int argc, char** argv) {
  using namespace lmcache::connector;
  std::string key(argv[1]);
  auto filename = key_to_filename(key);
  std::cout << filename << "\\n" << filename_to_key(filename) << "\\n"
            << get_chunk_hash_from_key(key) << "\\n";
}
""")
    executable = tmp_path / "key-codec"
    subprocess.run(
        [compiler, "-std=c++17", "-I", str(root), str(source), "-o", str(executable)],
        check=True,
        capture_output=True,
    )
    for salt in ("", "tenant"):
        for opaque_identity in ((), (KeyAttribute("dtype", "bf16"),)):
            key = ObjectKey(
                b"1234",
                "org/model",
                1,
                cache_salt=salt,
                opaque_identity=opaque_identity,
            )
            wire = _object_key_to_string(key)
            result = subprocess.check_output(
                [str(executable), wire], text=True
            ).splitlines()
            assert result == [_object_key_to_filename(key), wire, key.chunk_hash.hex()]


def test_bigtable_extended_unsalted_cannot_alias_legacy_salt() -> None:
    extended = ObjectKey(
        b"1234", "model", 1, opaque_identity=(KeyAttribute("dtype", "bf16"),)
    )
    legacy = replace(
        extended,
        opaque_identity=(),
        cache_salt=encode_matching_attributes(extended.opaque_identity, ()),
    )
    encoder = BigtableL2KeyEncoder()
    assert encoder.encode_row_key(extended) != encoder.encode_row_key(legacy)
