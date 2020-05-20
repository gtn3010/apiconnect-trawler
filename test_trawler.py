import trawler
import pytest
import datapower_net
import productstats_net
import requests_mock
import requests
from prometheus_client import REGISTRY
from kubernetes import client, config
from click.testing import CliRunner

boaty = trawler.Trawler()
boaty.secret_path = 'test-assets'


def test_check_nosettings():
    runner = CliRunner()
    result = runner.invoke(trawler.cli, ["--config", "/non/existent"])
    assert result.exit_code == 2


def test_check_config_load():
    boaty.load_config('test-assets/config.yaml')
    assert 'prometheus' in boaty.config
    assert 'graphite' in boaty.config
    assert boaty.config['graphite']['enabled'] is False


def test_trawl(caplog, mocker):
    boaty.config['nets'] = {}
    mocker.patch('time.sleep', side_effect=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
      print(boaty.config)
      boaty.in_cluster = True
      boaty.trawl_metrics()
    assert 'prometheus' in boaty.config
    assert 'graphite' in boaty.config
    assert 'INFO' in caplog.text


def test_secret():
    boaty.secrets_path = 'test-assets'
    content = boaty.read_secret('samplesecret')
    assert content == 'not-a-secret'


def test_missing_secret():
    boaty.secrets_path = 'test-assets'
    content = boaty.read_secret('missingsecret')
    assert content is None


def test_datapower_fishing(mocker):
    mocker.patch('kubernetes.config.load_incluster_config')
    mocker.patch('kubernetes.client.CoreV1Api.list_namespaced_pod')
    new_net = datapower_net.DataPowerNet({}, boaty)
    new_net.fish()
    assert config.load_incluster_config.called
    assert client.CoreV1Api.list_namespaced_pod.called


def test_datapower_instance(mocker, caplog):
    with requests_mock.mock() as m:
        m.put('https://127.0.0.1:5554/mgmt/config/apiconnect/Statistics/default', text="")
        dp = datapower_net.DataPower('127.0.0.1', '5554', 'myDp', 'admin', 'password')
        assert dp.name == 'myDp'
        assert dp.ip == '127.0.0.1'
        # Mock data
        mock_data = """
{
        "_links" : {
        "self" : {"href" : "/mgmt/status/default/LogTargetStatus"},
        "doc" : {"href" : "/mgmt/docs/status/LogTargetStatus"}},
        "LogTargetStatus" : {
        "LogTarget" : {"value": "default-log",
        "href" : "/mgmt/config/default/LogTarget/default-log"},
        "Status" : "active",
        "EventsProcessed" : 210938,
        "EventsDropped" : 0,
        "EventsPending" : 2,
        "ErrorInfo" : "none",
        "RequestedMemory" : 16}}
        """
        m.get('https://127.0.0.1:5554/mgmt/status/apiconnect/LogTargetStatus', text=mock_data)

        dp.fetch_data('LogTargetStatus', 'test')
        assert 'Creating gauges' in caplog.text
        # Lookup values from prometheus client
        assert REGISTRY.get_sample_value('test_EventsProcessed', labels={"pod": "myDp"}) == 210938
        assert REGISTRY.get_sample_value('test_EventsDropped', labels={"pod": "myDp"}) == 0
        assert REGISTRY.get_sample_value('test_EventsPending', labels={"pod": "myDp"}) == 2


def test_datapower_instance_readtimeout(caplog, mocker):
    mocker.patch('requests.put', side_effect=requests.exceptions.ReadTimeout())
    dp = datapower_net.DataPower('127.0.0.1', '5554', 'myDp', 'admin', 'password')
    assert dp.name == 'myDp'
    assert dp.ip == '127.0.0.1'
    assert 'rest-mgmt' in caplog.text


def test_datapower_instance_connecttimeout(caplog, mocker):
    mocker.patch('requests.put', side_effect=requests.exceptions.ConnectTimeout())
    dp = datapower_net.DataPower('127.0.0.1', '5554', 'myDp', 'admin', 'password')
    assert dp.name == 'myDp'
    assert dp.ip == '127.0.0.1'
    assert 'rest-mgmt' in caplog.text


def test_product_fishing(mocker):
    mocker.patch('kubernetes.config.load_incluster_config')
    mocker.patch('kubernetes.client.CoreV1Api.list_namespaced_service')
    with requests_mock.mock() as m:
        m.get(url='https://example.com', text='{"counts":{"blah":189}}')
    new_net = productstats_net.ProductStatsNet({}, boaty)
    assert new_net.password == 'not-a-password'
    assert config.load_incluster_config.called
    assert client.CoreV1Api.list_namespaced_service.called
