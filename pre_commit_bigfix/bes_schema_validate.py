"""A pre-commit hook to validate BigFix XML files against their schemas.

Covers BES and OJO files, Git External Custom Site files (siteConfig.xml,
site.xml, digest.xml) and BigFix Inventory signatures (Signatures/*.xml).
Only the schemas bundled with validate_bes_xml are used, never a *.xsd in the
current folder. Each error is printed as `path:line: message`; files that
pass print nothing. A .xml file whose root has no bundled schema (a sitemap
or a Maven site descriptor named site.xml, say) is not a BigFix file and is
skipped; a .bes or .ojo file with no schema fails.
"""

import argparse
import os
import sys

import validate_bes_xml

if __package__ in (None, ""):  # run directly as a script, not as a module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pre_commit_bigfix import bes_common


def build_argument_parser():
    """Build and return the argument parser."""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("filenames", nargs="*", help="Filenames to check.")

    return parser


def check_file(filename, schemas):
    """Validate one file; print its errors and return True if it failed."""

    result = validate_bes_xml.validate_bes(path=filename, schema_pathnames=schemas)
    if result:
        return False
    # compare against the value: every Status member is a non-empty str
    if result.status == "no_schema":
        if filename.lower().endswith(".xml"):
            return False  # not a BigFix file
        # inferred_schema is left out: it is cut short for namespaced roots
        print(f"{filename}: no schema to validate this file against")
        return True
    for line, message in result.errors:
        if line is None:
            print(f"{filename}: {message}")
        else:
            print(f"{filename}:{line}: {message}")
    if not result.errors:  # never expected, but a failure must say something
        print(f"{filename}: {result.status.value}")
    return True


def main(argv=None):
    """Main process."""

    # Parse command line arguments.
    argparser = build_argument_parser()
    args = argparser.parse_args(argv)

    if not args.filenames:
        return 0

    schemas = bes_common._bundled_schemas(  # pylint: disable=protected-access
        validate_bes_xml
    )
    if not schemas:
        # an empty list would make validate_bes_xml fall back to the cwd schemas
        print(
            "bes-schema-validate: validate_bes_xml has no bundled schemas; "
            'reinstall "validate_bes_xml>=2.4.1,<3"',
            file=sys.stderr,
        )
        return len(args.filenames)

    return sum(check_file(filename, schemas) for filename in args.filenames)


if __name__ == "__main__":
    sys.exit(main())
