def test_import_package():
    import trading_engine

    assert trading_engine.__version__ == "0.1.0"
