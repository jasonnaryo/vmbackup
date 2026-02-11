from agent import NetworkAgent


def test_infer_capacity_with_link_cap():
    a = NetworkAgent()
    assert a.infer_capacity_mbps(peak_down_mbps=900, link_speed_mbps=1000) == 1000


def test_infer_capacity_without_link_cap():
    a = NetworkAgent()
    assert a.infer_capacity_mbps(peak_down_mbps=210, link_speed_mbps=None) == 300


def test_connection_type_fiber():
    a = NetworkAgent()
    assert a.infer_connection_type(link_speed_mbps=1000, peak_down_mbps=120) == "fiber"


def test_connection_type_broadband():
    a = NetworkAgent()
    assert a.infer_connection_type(link_speed_mbps=100, peak_down_mbps=80) == "broadband"
