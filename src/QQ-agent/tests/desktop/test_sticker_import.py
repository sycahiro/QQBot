import base64
import io

from PIL import Image

from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.accounts import AccountStorage
from qqbot.storage.stickers import StickerStore

A = "12345678"


def jpeg_data(width=64, height=64, color="red", fmt="JPEG"):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, fmt)
    return buffer.getvalue()


def connected_bridge(tmp_path, store):
    instance = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path / "runtime"), lambda **_: None, stickers=store
    )
    instance._agent_workspace = lambda: {
        "source": "qq",
        "connection": {"connected": True, "account": {"uin": A}},
    }
    return instance


def store_for(tmp_path):
    accounts = AccountStorage(tmp_path / "accounts")
    database = accounts._open(A)["database"]
    return StickerStore(database)


def test_import_adds_a_cleaned_local_image_to_the_library(tmp_path):
    store = store_for(tmp_path)
    instance = connected_bridge(tmp_path, store)

    result = instance.import_sticker(
        base64.b64encode(jpeg_data()).decode(), "开心", ["笑脸"], "赞同群友", A
    )
    assert result["ok"] is True and result["account"] == A
    assert result["item"]["collected"] is True
    assert result["item"]["note"] == "开心"

    listed = store.list(A)
    assert len(listed) == 1 and listed[0]["tags"] == ["笑脸"]


def test_import_of_the_same_bytes_reports_a_duplicate(tmp_path):
    store = store_for(tmp_path)
    instance = connected_bridge(tmp_path, store)
    data = base64.b64encode(jpeg_data()).decode()

    first = instance.import_sticker(data, "", [], "", A)
    second = instance.import_sticker(data, "", [], "", A)
    assert first["ok"] and second["ok"]
    assert first["item"]["collected"] is True
    assert second["item"]["duplicate"] is True
    assert len(store.list(A)) == 1


def test_import_supports_animated_gif_first_frame(tmp_path):
    store = store_for(tmp_path)
    instance = connected_bridge(tmp_path, store)
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(
        buffer, "GIF", save_all=True, append_images=[Image.new("RGB", (64, 64), "blue")]
    )
    result = instance.import_sticker(base64.b64encode(buffer.getvalue()).decode(), "", [], "", A)
    assert result["ok"] is True
    assert result["item"]["firstFrame"] is True


def test_import_rejects_oversized_payload_invalid_base64_and_broken_images(tmp_path):
    store = store_for(tmp_path)
    instance = connected_bridge(tmp_path, store)

    oversized = instance.import_sticker("A" * (20 * 1024 * 1024 + 1), "", [], "", A)
    assert oversized["ok"] is False and oversized["error"]["code"] == "INVALID_INPUT"

    broken = instance.import_sticker("not-base64!!", "", [], "", A)
    assert broken["ok"] is False and "图片数据无效" in broken["error"]["message"]

    garbage = instance.import_sticker(
        base64.b64encode(b"definitely not an image").decode(), "", [], "", A
    )
    assert garbage["ok"] is False and "图片损坏" in garbage["error"]["message"]
    assert store.list(A) == []


def test_import_requires_a_connected_account(tmp_path):
    instance = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path / "runtime"),
        lambda **_: None,
        stickers=store_for(tmp_path),
    )
    result = instance.import_sticker(base64.b64encode(jpeg_data()).decode(), "", [], "", A)
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"
