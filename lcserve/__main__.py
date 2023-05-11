import os
import sys
from typing import List, Union

import click
import yaml
from jcloud.constants import Phase
from jina import Flow

from . import __version__
from .errors import InvalidAutoscaleMinError, InvalidInstanceError
from .flow import (
    APP_NAME,
    AUTOGPT_APP_NAME,
    BABYAGI_APP_NAME,
    DEFAULT_TIMEOUT,
    PANDAS_AI_APP_NAME,
    PDF_QNA_APP_NAME,
    deploy_app_on_jcloud,
    get_app_dir,
    get_app_status_on_jcloud,
    get_flow_dict,
    get_flow_yaml,
    list_apps_on_jcloud,
    load_local_df,
    push_app_to_hubble,
    remove_app_on_jcloud,
    resolve_jcloud_config,
    syncify,
    update_requirements,
)
from .utils import validate_jcloud_config


def serve_locally(module: Union[str, List[str]], port: int = 8080):
    sys.path.append(os.getcwd())
    f_yaml = get_flow_yaml(module, jcloud=False, port=port)
    with Flow.load_config(f_yaml) as f:
        # TODO: add local description
        f.block()


async def serve_on_jcloud(
    module: Union[str, List[str]],
    name: str = APP_NAME,
    requirements: List[str] = None,
    app_id: str = None,
    version: str = 'latest',
    timeout: int = DEFAULT_TIMEOUT,
    platform: str = None,
    config: str = None,
    verbose: bool = False,
):
    from .backend.playground.utils.helper import get_random_tag

    app, app_dir = get_app_dir(module)
    config = resolve_jcloud_config(config, app_dir)

    tag = get_random_tag()
    gateway_id_wo_tag, is_websocket = push_app_to_hubble(
        app,
        app_dir,
        requirements=requirements,
        tag=tag,
        version=version,
        platform=platform,
        verbose=verbose,
    )
    app_id, _ = await deploy_app_on_jcloud(
        flow_dict=get_flow_dict(
            module=module,
            jcloud=True,
            port=8080,
            name=name,
            timeout=timeout,
            app_id=app_id,
            gateway_id=gateway_id_wo_tag + ':' + tag,
            is_websocket=is_websocket,
            jcloud_config_path=config,
        ),
        app_id=app_id,
        verbose=verbose,
    )
    await get_app_status_on_jcloud(app_id=app_id)
    return app_id


async def serve_babyagi_on_jcloud(
    name: str = BABYAGI_APP_NAME,
    requirements: List[str] = None,
    app_id: str = None,
    version: str = 'latest',
    timeout: int = DEFAULT_TIMEOUT,
    platform: str = None,
    config: str = None,
    verbose: bool = False,
):
    requirements = requirements or []
    update_requirements(
        path=os.path.join(
            os.path.dirname(__file__), 'apps', 'babyagi', 'requirements.txt'
        ),
        requirements=requirements,
    )
    await serve_on_jcloud(
        module='lcserve.apps.babyagi.app',
        name=name,
        requirements=requirements,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


async def serve_autogpt_on_jcloud(
    name: str = AUTOGPT_APP_NAME,
    requirements: List[str] = None,
    app_id: str = None,
    version: str = 'latest',
    timeout: int = DEFAULT_TIMEOUT,
    platform: str = None,
    config: str = None,
    verbose: bool = False,
):
    requirements = requirements or []
    update_requirements(
        path=os.path.join(
            os.path.dirname(__file__), 'apps', 'autogpt', 'requirements.txt'
        ),
        requirements=requirements,
    )
    await serve_on_jcloud(
        module='lcserve.apps.autogpt.app',
        name=name,
        requirements=tuple(requirements),
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


async def serve_pdf_qna_on_jcloud(
    name: str = PDF_QNA_APP_NAME,
    app_id: str = None,
    version: str = 'latest',
    timeout: int = DEFAULT_TIMEOUT,
    platform: str = None,
    config: str = None,
    verbose: bool = False,
):
    await serve_on_jcloud(
        module='lcserve.apps.pdf_qna.app',
        name=name,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


async def serve_pandas_ai_on_jcloud(
    name: str = PANDAS_AI_APP_NAME,
    app_id: str = None,
    version: str = 'latest',
    timeout: int = DEFAULT_TIMEOUT,
    platform: str = None,
    config: str = None,
    verbose: bool = False,
):
    await serve_on_jcloud(
        module='lcserve.apps.pandas_ai.api',
        name=name,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


def upload_df_to_jcloud(module: str, name: str):
    from . import upload_df

    df = load_local_df(module)
    df_id = upload_df(df, name)
    click.echo(
        "Uploaded dataframe with ID " + click.style(df_id, fg="green", bold=True)
    )


def validate_jcloud_config_callback(ctx, param, value):
    if not value:
        return None
    try:
        validate_jcloud_config(value)
    except InvalidInstanceError as e:
        raise click.BadParameter(
            f"Invalid instance '{e.instance}' found in config file', please refer to https://docs.jina.ai/concepts/jcloud/configuration/#cpu-tiers for instance definition."
        )
    except InvalidAutoscaleMinError as e:
        raise click.BadParameter(
            f"Invalid instance '{e.min}' found in config file', it should be a number >= 0."
        )

    return value


jcloud_shared_options = [
    click.option(
        '--app-id',
        type=str,
        default=None,
        help='AppID of the deployed agent to be updated.',
        show_default=True,
    ),
    click.option(
        '--version',
        type=str,
        default='latest',
        help='Version of serving gateway to be used.',
        show_default=False,
    ),
    click.option(
        '--timeout',
        type=int,
        default=DEFAULT_TIMEOUT,
        help='Total request timeout in seconds.',
        show_default=True,
    ),
    click.option(
        '--platform',
        type=str,
        default=None,
        help='Platform of Docker image needed for the deployment is built on.',
        show_default=False,
    ),
    click.option(
        '--config',
        type=click.Path(exists=True),
        help='Path to the config file',
        callback=validate_jcloud_config_callback,
        show_default=False,
    ),
    click.option(
        '--verbose',
        is_flag=True,
        help='Verbose mode.',
        show_default=True,
    ),
]


def add_jcloud_shared_options(func):
    for option in reversed(jcloud_shared_options):
        func = option(func)
    return func


@click.group()
@click.version_option(__version__, '-v', '--version', prog_name='lc-serve')
@click.help_option('-h', '--help')
def serve():
    pass


@serve.group(help='Deploy the app.')
@click.help_option('-h', '--help')
def deploy():
    pass


@deploy.command(help='Deploy the app locally.')
@click.argument(
    'module',
    type=str,
    required=True,
)
@click.option(
    '--port',
    type=int,
    default=8080,
    help='Port to run the server on.',
)
@click.help_option('-h', '--help')
def local(module, port):
    serve_locally(module, port=port)


@deploy.command(help='Deploy the app on JCloud.')
@click.argument(
    'module',
    type=str,
    required=True,
)
@click.option(
    '--name',
    type=str,
    default=APP_NAME,
    help='Name of the app.',
    show_default=True,
)
@add_jcloud_shared_options
@click.help_option('-h', '--help')
@syncify
async def jcloud(module, name, app_id, version, timeout, platform, config, verbose):
    await serve_on_jcloud(
        module,
        name=name,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


@deploy.command(help='Deploy babyagi on JCloud.')
@click.option(
    '--name',
    type=str,
    default=BABYAGI_APP_NAME,
    help='Name of the app.',
    show_default=True,
)
@click.option(
    '--requirements',
    default=None,
    help='List of requirements to be installed.',
    multiple=True,
)
@add_jcloud_shared_options
@click.help_option('-h', '--help')
@syncify
async def babyagi(
    name, requirements, app_id, version, timeout, platform, config, verbose
):
    await serve_babyagi_on_jcloud(
        name=name,
        requirements=requirements,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


@deploy.command(help='Deploy pdf qna on JCloud.')
@click.option(
    '--name',
    type=str,
    default=PDF_QNA_APP_NAME,
    help='Name of the app.',
    show_default=True,
)
@add_jcloud_shared_options
@click.help_option('-h', '--help')
@syncify
async def pdf_qna(name, app_id, version, timeout, platform, config, verbose):
    await serve_pdf_qna_on_jcloud(
        name=name,
        app_id=app_id,
        version=version,
        timeout=timeout,
        config=config,
        platform=platform,
        verbose=verbose,
    )


@deploy.command(help='Deploy autogpt on JCloud.')
@click.option(
    '--name',
    type=str,
    default=AUTOGPT_APP_NAME,
    help='Name of the app.',
    show_default=True,
)
@click.option(
    '--requirements',
    default=None,
    help='List of requirements to be installed.',
    multiple=True,
)
@add_jcloud_shared_options
@click.help_option('-h', '--help')
@syncify
async def autogpt(
    name, requirements, app_id, version, timeout, platform, config, verbose
):
    await serve_autogpt_on_jcloud(
        name=name,
        requirements=requirements,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


@deploy.command(help='Deploy pandas-ai on JCloud.')
@click.option(
    '--name',
    type=str,
    default=PANDAS_AI_APP_NAME,
    help='Name of the app.',
    show_default=True,
)
@add_jcloud_shared_options
@click.help_option('-h', '--help')
@syncify
async def pandas_ai(name, app_id, version, timeout, platform, config, verbose):
    await serve_pandas_ai_on_jcloud(
        name=name,
        app_id=app_id,
        version=version,
        timeout=timeout,
        platform=platform,
        config=config,
        verbose=verbose,
    )


@serve.group(help='Utility commands for lc-serve.')
@click.help_option('-h', '--help')
def util():
    pass


@util.command(help='Upload a DataFrame to JCloud.')
@click.argument(
    'module',
    type=str,
    required=True,
)
@click.option(
    '--name',
    type=str,
    help='Name of the DataFrame.',
)
def upload_df(module, name):
    upload_df_to_jcloud(module, name)


@serve.command(help='List all deployed apps.')
@click.option(
    '--phase',
    type=str,
    default=','.join(
        [
            Phase.Serving,
            Phase.Failed,
            Phase.Starting,
            Phase.Updating,
            Phase.Paused,
        ]
    ),
    help='Deployment phase for the app.',
    show_default=True,
)
@click.option(
    '--name',
    type=str,
    default=None,
    help='Name of the app.',
    show_default=True,
)
@click.help_option('-h', '--help')
@syncify
async def list(phase, name):
    await list_apps_on_jcloud(phase=phase, name=name)


@serve.command(help='Get status of a deployed app.')
@click.argument('app-id')
@click.help_option('-h', '--help')
@syncify
async def status(app_id):
    await get_app_status_on_jcloud(app_id)


@serve.command(help='Remove an app.')
@click.argument('app-id')
@click.help_option('-h', '--help')
@syncify
async def remove(app_id):
    await remove_app_on_jcloud(app_id)


@serve.group(help='Play with predefined apps on JCloud.')
@click.help_option('-h', '--help')
def playground():
    pass


@playground.command(help='Play with babyagi on JCloud.')
@click.option(
    '--verbose',
    is_flag=True,
    help='Verbose mode.',
    show_default=True,
)
def babyagi(verbose):
    sys.path.append(os.path.join(os.path.dirname(__file__), 'playground', 'babyagi'))
    from .playground.babyagi.playground import play

    play(verbose=verbose)


@playground.command(help='Play with autogpt on JCloud.')
@click.option(
    '--verbose',
    is_flag=True,
    help='Verbose mode.',
    show_default=True,
)
@syncify
async def autogpt(verbose):
    sys.path.append(os.path.join(os.path.dirname(__file__), 'playground', 'autogpt'))
    from .playground.autogpt.playground import play

    await play(verbose=verbose)


@playground.command(help='Play with pdf qna on JCloud.')
def pdf_qna():
    try:
        from streamlit.web import cli as strcli
    except ImportError:
        raise ImportError(
            "Streamlit is not installed. Please install it with `pip install streamlit`."
        )

    sys.argv = [
        'streamlit',
        'run',
        os.path.join(
            os.path.dirname(__file__), 'playground', 'pdf_qna', 'playground.py'
        ),
    ]
    sys.exit(strcli.main())


@playground.command(help='Play with pandas-ai on JCloud.')
@click.argument(
    'host',
    type=str,
    required=True,
)
@click.option(
    '--verbose',
    is_flag=True,
    help='Verbose mode.',
    show_default=True,
)
@syncify
async def pandas_ai(host, verbose):
    sys.path.append(os.path.join(os.path.dirname(__file__), 'playground', 'pandas_ai'))
    from .playground.pandas_ai.playground import converse

    await converse(host=host, verbose=verbose)


if __name__ == "__main__":
    serve()
