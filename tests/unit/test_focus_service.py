from backend.services.focus import FocusService


def test_make_dest_sanitises_and_is_unique(tmp_path):
    svc = FocusService(None, None, None, tmp_path)
    a = svc._make_dest("../evil name/")
    b = svc._make_dest("../evil name/")
    assert a != b and a.parent == tmp_path / "stacks" and b.is_dir()
    assert ".." not in a.name and "/" not in a.name
    assert svc._make_dest(None).is_dir()
