#!/usr/bin/python3

"""Helps automate grading programming assignments submitted to Blackboard.

Setup for UTSA CS 1713, which teaches simple C programming.
Takes a zipfile generated from the web GUI and creates students directories.
For each student it runs their C program and saves the output.
"""

import argparse
import glob
import os
import re
import shutil
import tarfile
import zipfile

from difflib import unified_diff
from functools import partial
from subprocess import check_output, STDOUT, CalledProcessError, TimeoutExpired

# Various directories for output
TEMP_DIR = 'temp'
SUBS_DIR = 'submissions'
RUN_DIR = 'run'

# Name strings for student files
INFO_FILE = 'info-{0}.txt'
OUTPUT_FILE = 'out-{0}.txt'
GRADING_FILE = 'grading-{0}.txt'
DIFF_FILE = 'diff-{0}.diff'
PRINT_FILE = 'prints-{0}.txt'
COND_CORR_FILE = 'condensed_output.txt'

# REs to identity and rename things
INFO_FILE_RE = re.compile(r'.+_attempt_[0-9-]{19}\.txt')
STUD_ID_RE = re.compile(r'^Name:.+\((.+)\)$')
ORIG_FILE_RE = re.compile(r'^\tOriginal filename: (.+)$')
FILE_RE = re.compile(r'^\tFilename: (.+)$')


open_utf8 = partial(open, encoding='utf-8', errors='replace')


def collapse_whitespace(lines):
    """Trims ends and collapses whitespace sequences into single space."""

    collapsed = []

    for line in lines:
        line = re.sub(r'^\s+', '', line)
        line = re.sub(r'\s+$', '\n', line)
        line = re.sub(r'\s{2,}', ' ', line)

        if line:
            collapsed.append(line)

    return collapsed


def find_output_calls(lines):
    """Finds and returns lines with calls to printf or write."""

    matches = []

    for line in lines:
        match = re.match(r'.+(printf|write) *\(.+', line)
        if match:
            matches.append(line)

    return matches


def get_args():
    """Create arg parser, parse and return them."""

    parser = argparse.ArgumentParser(
        description='Help automate grading for CS 1713.'
    )

    parser.add_argument(
        '-d',
        '--directory',
        default='.',
        help='Directory you want to grade.'
    )
    parser.add_argument(
        '-z',
        '--zipfile',
        default="blackboard.zip",
        help='Zipfile from Blackboard.'
    )
    parser.add_argument(
        '-r',
        '--resources',
        default='resources',
        help='Directory with compliation resources.'
    )
    parser.add_argument(
        '-c',
        '--commands',
        default='commands.txt',
        help='Text file with line separated commands to run.'
    )
    parser.add_argument(
        '-o',
        '--correct-output',
        default='output.txt',
        help='File with correct output.'
    )
    parser.add_argument(
        '-g',
        '--regrade',
        help='ID for student you want to regrade.'
    )

    return parser.parse_args()


def glob_commands(lines):
    """Globs commands without using a shell."""

    commands = []
    for line in lines:
        args = []
        for token in line.split():
            if '*' in token:
                globs = glob.glob(token)
                args.append(globs[0] if len(globs) == 1 else token)
            elif './' in token:
                args.append(os.path.abspath(token))
            else:
                args.append(token)
        commands.append(args)

    return commands


def print_err(err, stud_id, gfile):
    """Print error to stdout and grading file."""

    print('!!! ({0}) {1}'.format(stud_id, str(err)))
    print('!!! ({0}) {1}'.format(stud_id, str(err)), file=gfile)


def run(corr_out, cmds, rpath):
    """Compiles and runs code in temp directory."""

    stud_id = os.path.basename(os.getcwd())

    # Going to run submission in temp subdirectory
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.mkdir(TEMP_DIR)

    # Copy default resources into temp directory
    for fname in os.listdir(rpath):
        shutil.copy(os.path.join(rpath, fname), os.path.join(TEMP_DIR, fname))

    # Copy student resources into temp directory
    fnames = (fname for fname in os.listdir('.') if os.path.isfile(fname))
    for fname in fnames:
        shutil.copy(fname, os.path.join(TEMP_DIR, fname))

    # Open grading and analysis files
    gfile = open_utf8(GRADING_FILE.format(stud_id), 'w')
    ofile = open_utf8(OUTPUT_FILE.format(stud_id), 'w')
    pfile = open_utf8(PRINT_FILE.format(stud_id), 'w')
    dfile = open_utf8(DIFF_FILE.format(stud_id), 'w')

    print('Grading for {0}.'.format(stud_id), file=gfile)

    # Find output calls in source files to check for obvious cheating.
    # e.g. printf("LINE OF CORRECT OUTPUT");
    fnames = (fname for fname in os.listdir('.') if fname.endswith('.c'))
    for fname in fnames:
        with open_utf8(fname) as source:
            try:
                lines = source.readlines()
            except UnicodeDecodeError as err:
                print_err(err, stud_id, gfile)
                return

            calls = find_output_calls(lines)
            pfile.writelines(calls)

    os.chdir(TEMP_DIR)

    # Need to get absolute paths for binary files
    commands = glob_commands(cmds)

    output = []
    for cmd in commands:
        try:
            out_bytes = check_output(
                cmd,
                stderr=STDOUT,
                timeout=5
            )
            out_str = str(out_bytes, encoding='utf-8', errors='replace')
            output.extend(out_str.splitlines(keepends=True))
        except (CalledProcessError, FileNotFoundError, TimeoutExpired) as err:
            print_err(err, stud_id, gfile)
            if isinstance(err, CalledProcessError):
                print(str(err.output), file=gfile)
            return

    print('', file=gfile)
    print('Score: ', file=gfile)
    print('Grader: {0}'.format(os.getenv('GRADER', '')), file=gfile)

    if output:
        output = collapse_whitespace(output)
        ofile.writelines(output)
        diff = unified_diff(
            corr_out,
            output,
            fromfile='correct',
            tofile='student'
        )
        dfile.writelines(diff)

    gfile.close()
    ofile.close()
    pfile.close()
    os.chdir('..')
    shutil.rmtree(TEMP_DIR)


def main():
    """
    1. Unzip file from Blackboard
    2. Create student directories
    3. Rename files
    4. Run commands.txt
    """

    args = get_args()

    directory = os.path.abspath(args.directory)
    rpath = os.path.abspath(args.resources)

    with open_utf8(args.commands) as cfile:
        cmds = cfile.readlines()

    with open_utf8(args.correct_output) as cofile:
        corr_out = cofile.readlines()
        corr_out = collapse_whitespace(corr_out)
        with open_utf8(COND_CORR_FILE, 'w') as ccofile:
            ccofile.writelines(corr_out)

    os.chdir(directory)

    # Just rerun for single student
    if args.regrade:
        stud_id = args.regrade
        os.chdir(os.path.join(SUBS_DIR, stud_id))
        run(corr_out, cmds, rpath)
        exit()

    archive = zipfile.ZipFile(args.zipfile, 'r')

    # Make top-level directories
    if os.path.exists(SUBS_DIR):
        shutil.rmtree(SUBS_DIR)
    os.mkdir(SUBS_DIR)

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.mkdir(TEMP_DIR)

    # Extract the zipfile to temp directory
    archive.extractall(TEMP_DIR)
    archive.close()

    # Traverse temp directory, looking for submission info files to process
    for raw_fname in os.listdir(TEMP_DIR):
        re_match = INFO_FILE_RE.search(raw_fname)

        if not re_match:
            continue

        # Process the info file
        # Info file maps actual submissions to Blackboard's ugly zipfile names
        ifname = os.path.join(TEMP_DIR, raw_fname)
        with open_utf8(ifname) as ifile:
            stud_id = None
            orig_fname = None

            for line in ifile.readlines():

                # Line with the student's name / ID
                re_match = STUD_ID_RE.search(line)
                if re_match:
                    stud_id = re_match.group(1)
                    os.mkdir(os.path.join(SUBS_DIR, stud_id))
                    os.rename(ifile.name, os.path.join(
                        SUBS_DIR, stud_id, INFO_FILE.format(stud_id)))
                    continue

                # Line with an original filename (as the student submitted)
                re_match = ORIG_FILE_RE.search(line)
                if re_match:
                    orig_fname = re_match.group(1)
                    continue

                # Line with the filename as it is in the zipfile
                re_match = FILE_RE.search(line)
                if re_match:
                    raw_fname = re_match.group(1)
                    os.rename(
                        os.path.join(TEMP_DIR, raw_fname),
                        os.path.join(SUBS_DIR, stud_id, orig_fname)
                    )
                    continue

        # Uncompress archive files if any
        os.chdir(os.path.join(SUBS_DIR, stud_id))
        for fname in os.listdir('.'):
            name, ext = os.path.splitext(fname)

            if ext in ('.zip', '.tar', '.gz'):
                if ext == '.zip':
                    zfile = zipfile.ZipFile(fname, 'r')
                    zfile.extractall()
                    zfile.close()
                elif ext == '.tar':
                    tfile = tarfile.open(fname, 'r')
                    tfile.extractall()
                    tfile.close()
                elif ext == '.gz':
                    tfile = tarfile.open(fname, 'r:gz')
                    tfile.extractall()
                    tfile.close()


                os.remove(fname)

            if os.path.isdir(name):
                for unzip_file in os.listdir(name):
                    os.rename(os.path.join(name, unzip_file), unzip_file)
                shutil.rmtree(name)

        # Run submission in 'temp/run'
        run(corr_out, cmds, rpath)

        os.chdir(directory)


if __name__ == '__main__':
    main()
