import json
import pytest
from app.core.config import Settings
from app.execution.cancellation import CancellationHub
from app.operations.cli import main
from app.operations.controller import Controller
from app.operations.fakes import FakeBackend
from app.operations.models import Configuration


def setup():
    settings=Settings(operations=Configuration(enabled=True,screenshot_enabled=True))
    backend=FakeBackend()
    return settings,backend,Controller(settings.operations,backend=backend,hub=CancellationHub())


@pytest.mark.parametrize('args,answer',[
    (['manual-volume-test','increase'],'APPROVE system.volume.increase'),
    (['manual-volume-test','decrease'],'APPROVE system.volume.decrease'),
    (['manual-volume-test','set','40'],'APPROVE system.volume.set 40'),
    (['manual-volume-test','mute'],'APPROVE system.volume.mute'),
    (['manual-volume-test','unmute'],'APPROVE system.volume.unmute'),
    (['manual-brightness-test','set','60'],'APPROVE system.brightness.set 60')])
def test_exact_operator_commands(args,answer):
    settings,backend,driver=setup();output=[]
    code=main(args,settings=settings,controller=driver,read=lambda _:answer,write=output.append,interactive=lambda:True)
    assert code==0 and 'not voice authentication' in output[0]
    assert json.loads(output[-1])['verified']


@pytest.mark.parametrize('args',[
    ['manual-volume-test','set','40.0'],['manual-volume-test','set','-1'],['manual-volume-test','set','101'],
    ['manual-volume-test','set'],['manual-volume-test','mute','40'],['manual-volume-test','mute','--confirmed=true'],
    ['manual-screenshot-test','C:/PRIVATE_MARKER'],['manual-brightness-test','mute'],
    ['delete-screenshot','PRIVATE_MARKER'],['manual-volume-test','increase','decrease']])
def test_bad_cli_no_effect_no_echo(args):
    settings,backend,driver=setup();output=[]
    assert main(args,settings=settings,controller=driver,read=lambda _:pytest.fail('prompted'),write=output.append,interactive=lambda:True)==2
    assert not backend.mutations and 'PRIVATE_MARKER' not in str(output)


@pytest.mark.parametrize('tty,answer',[(False,'APPROVE system.volume.mute'),(True,'yes'),(True,'confirmed=true')])
def test_no_piped_or_implicit_confirmation(tty,answer):
    settings,backend,driver=setup()
    assert main(['manual-volume-test','mute'],settings=settings,controller=driver,read=lambda _:answer,write=lambda _:None,interactive=lambda:tty)==2
    assert not backend.mutations


@pytest.mark.parametrize('command',['status','volume-status','mute-status','brightness-status','history','authenticated-voice-status'])
def test_read_only_commands(command):
    settings,backend,driver=setup()
    assert main([command],settings=settings,controller=driver,read=lambda _:pytest.fail('prompted'),write=lambda _:None)==0
    assert not backend.mutations


def test_voice_pending_denies_before_every_integration():
    class Forbidden:
        def __getattr__(self,name):pytest.fail('forbidden_voice_integration')
    output=[]
    assert main(['authenticated-voice'],settings=Settings(),controller=Forbidden(),read=lambda _:pytest.fail('prompted'),write=output.append)==2
    assert json.loads(output[-1])['reason']=='calibration_pending'


def test_session_history_and_stop():
    settings,backend,driver=setup()
    answers=iter(['volume-status','history','stop','exit']);output=[]
    assert main(['session'],settings=settings,controller=driver,read=lambda _:next(answers),write=output.append,interactive=lambda:True)==0
    assert any('history' in value and 'state_read_and_verified' in value for value in output)
    assert driver.hub.stopped.is_set() and not backend.mutations



def test_screenshot_capture_and_selected_delete_commands_require_exact_consent():
    from app.operations.fakes import FakeStore
    settings, backend, driver = setup()
    driver.store = FakeStore()
    output = []
    assert main(["manual-screenshot-test"], settings=settings, controller=driver,
                read=lambda _: "APPROVE screen.screenshot.capture", write=output.append,
                interactive=lambda: True) == 0
    assert any("capture AND local saving" in line for line in output)
    artifact = json.loads(output[-1])["artifact_id"]
    assert main(["delete-screenshot", artifact], settings=settings, controller=driver,
                read=lambda _: "APPROVE screen.screenshot.delete " + artifact,
                write=output.append, interactive=lambda: True) == 0
    assert not driver.store.images
    assert json.loads(output[-1])["code"] == "selected_artifact_deleted_and_verified"
