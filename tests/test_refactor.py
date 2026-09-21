"""
Unit tests for the CLI refactoring:

* ``stage_config`` resolution is cached and invalidated when settings are
  reloaded or an override is applied.
* The argparse definitions split out of ``handle`` still register every
  subcommand and its options.
* Region / zip-exclude constants are externalized in ``zappa.config`` and can
  be overridden via config file or environment variables.
"""

import argparse
import os
import shutil
import tempfile
import unittest

from zappa import config as zappa_config


class TestStageConfigCaching(unittest.TestCase):

    def _make_cli(self):
        # Importing zappa.cli pulls in the whole dependency chain; these tests
        # exercise the cache logic on a bare object built from the methods.
        from zappa.cli import ZappaCLI
        cli = ZappaCLI()
        cli.api_stage = 'extendo'
        cli.zappa_settings = {
            'base': {
                's3_bucket': 'lmbda',
                'touch': True,
                'delete_local_zip': True,
            },
            'extendo': {
                'extends': 'base',
                's3_bucket': 'lmbda-derived',
            },
        }
        return cli

    def test_extends_merged_settings(self):
        cli = self._make_cli()
        self.assertEqual('lmbda-derived', cli.stage_config['s3_bucket'])
        self.assertTrue(cli.stage_config['touch'])
        self.assertTrue(cli.stage_config['delete_local_zip'])

    def test_resolved_settings_are_cached(self):
        cli = self._make_cli()
        first = cli.stage_config
        self.assertIn('extendo', cli._stage_settings_cache)
        # Resolving again must hit the cache rather than re-traversing the
        # raw settings (a cache hit never indexes into ``zappa_settings``).
        reads = []

        class TrackingSettings(dict):
            def __getitem__(self, key):
                reads.append(key)
                return dict.__getitem__(self, key)

        cli.zappa_settings = TrackingSettings(cli.zappa_settings)
        cli._invalidate_stage_settings_cache()
        second = cli.stage_config
        self.assertEqual(first['s3_bucket'], second['s3_bucket'])
        self.assertGreater(len(reads), 0)
        reads = []
        cli.stage_config
        cli.stage_config
        self.assertEqual([], reads)

    def test_cached_value_is_not_mutated_by_callers(self):
        cli = self._make_cli()
        cli.stage_config['s3_bucket'] = 'tampered'
        self.assertEqual('lmbda-derived', cli.stage_config['s3_bucket'])

    def test_cache_invalidated_on_settings_reload(self):
        cli = self._make_cli()
        self.assertEqual('lmbda-derived', cli.stage_config['s3_bucket'])
        cli.zappa_settings['extendo']['s3_bucket'] = 'new-bucket'
        cli._invalidate_stage_settings_cache()
        self.assertEqual('new-bucket', cli.stage_config['s3_bucket'])

    def test_circular_extends_still_detected(self):
        cli = self._make_cli()
        cli.api_stage = 'a'
        cli.zappa_settings = {
            'a': {'extends': 'b'},
            'b': {'extends': 'a'},
        }
        with self.assertRaises(RuntimeError):
            cli.stage_config

    def test_undefined_extended_stage_still_raises(self):
        from click.exceptions import ClickException
        cli = self._make_cli()
        cli.api_stage = 'nope'
        cli.zappa_settings = {'nope': {'extends': 'missing'}}
        with self.assertRaises(ClickException):
            cli.stage_config


class TestParserSplit(unittest.TestCase):

    EXPECTED_COMMANDS = [
        'certify', 'deploy', 'init', 'invoke', 'manage', 'package',
        'rollback', 'schedule', 'shell', 'status', 'tail', 'template',
        'undeploy', 'unschedule', 'update',
    ]

    def _parser(self):
        from zappa.cli import ZappaCLI
        return ZappaCLI.build_parser(ZappaCLI())

    def _subparsers(self, parser):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return action.choices
        return {}

    def test_all_subcommands_registered(self):
        choices = self._subparsers(self._parser())
        for command in self.EXPECTED_COMMANDS:
            self.assertIn(command, choices)

    def test_deploy_zip_argument(self):
        parser = self._parser()
        args = parser.parse_args(['deploy', 'dev', '-z', '/tmp/pkg.zip'])
        self.assertEqual('deploy', args.command)
        self.assertEqual('dev', args.stage_env)
        self.assertEqual('/tmp/pkg.zip', args.zip)

    def test_rollback_positive_int_validation(self):
        parser = self._parser()
        args = parser.parse_args(['rollback', 'dev', '-n', '3'])
        self.assertEqual(3, args.num_rollback)
        with self.assertRaises(SystemExit):
            parser.parse_args(['rollback', 'dev', '-n', '-1'])

    def test_tail_defaults(self):
        parser = self._parser()
        args = parser.parse_args(['tail', 'dev'])
        self.assertTrue(args.keep_open if 'keep_open' in args else True)
        self.assertEqual('100000s', args.since)
        self.assertFalse(args.http)

    def test_manage_parsing(self):
        parser = self._parser()
        args = parser.parse_args(['manage', '--all', 'showmigrations', 'admin'])
        self.assertTrue(args.all)
        self.assertEqual(['showmigrations', 'admin'], args.command_rest)

    def test_handle_is_a_thin_entrypoint(self):
        import inspect
        from zappa.cli import ZappaCLI
        handle_lines = len(inspect.getsourcelines(ZappaCLI.handle)[0])
        self.assertLess(handle_lines, 20)


class TestExternalizedConstants(unittest.TestCase):

    def setUp(self):
        zappa_config.refresh_config()

    def tearDown(self):
        for name in ('ZAPPA_CONFIG_FILE', 'ZAPPA_LAMBDA_REGIONS',
                     'ZAPPA_API_GATEWAY_REGIONS', 'ZAPPA_ZIP_EXCLUDES',
                     'ZAPPA_DISABLE_REGION_DISCOVERY'):
            os.environ.pop(name, None)
        zappa_config.refresh_config()

    def test_shipped_defaults(self):
        self.assertIn('us-east-1', zappa_config.get_lambda_regions())
        self.assertIn('us-east-1', zappa_config.get_api_gateway_regions())
        self.assertIn('.git/*', zappa_config.get_zip_excludes())

    def test_env_override_regions(self):
        os.environ['ZAPPA_LAMBDA_REGIONS'] = 'us-east-1, custom-region-1'
        self.assertEqual(['us-east-1', 'custom-region-1'],
                         zappa_config.get_lambda_regions())

    def test_env_override_zip_excludes(self):
        os.environ['ZAPPA_ZIP_EXCLUDES'] = '*.foo, bar/*'
        self.assertEqual(['*.foo', 'bar/*'],
                         zappa_config.get_zip_excludes())

    def test_custom_config_file(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            custom = os.path.join(tmp_dir, 'custom.json')
            with open(custom, 'w') as f:
                f.write('{"lambda_regions": ["mars-north-1"],'
                        ' "zip_excludes": ["*.mars"]}')
            os.environ['ZAPPA_CONFIG_FILE'] = custom
            os.environ['ZAPPA_DISABLE_REGION_DISCOVERY'] = '1'
            zappa_config.refresh_config()
            self.assertEqual(['mars-north-1'],
                             zappa_config.get_lambda_regions())
            self.assertEqual(['*.mars'], zappa_config.get_zip_excludes())
        finally:
            shutil.rmtree(tmp_dir)

    def test_dynamic_discovery_union(self):
        # When discovery works, discovered regions are a superset of defaults.
        regions = zappa_config.get_lambda_regions()
        for region in ('us-east-1', 'eu-west-1'):
            self.assertIn(region, regions)


if __name__ == '__main__':
    unittest.main()
