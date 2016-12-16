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
import time
import zipfile

from difflib import unified_diff
from functools import partial
from subprocess import check_output, STDOUT, CalledProcessError, SubprocessError

# Various directories for output
TEMP_DIR = 'temp'
SUBS_DIR = 'submissions'
RUN_DIR = 'run'

# Name strings for student files
INFO_FILE = 'info-{0}.txt'
OUTPUT_RAW_FILE = 'raw-out-{0}.txt'
OUTPUT_COND_FILE = 'cond-out-{0}.txt'
GRADING_FILE = 'grading-{0}.txt'
DIFF_FILE = 'diff-{0}.diff'
PRINT_FILE = 'prints-{0}.txt'
COND_CORR_FILE = 'condensed-output.txt'
ERR_FILE = 'errors.txt'
RUN_FILE = '{0}-run.txt'

# REs to identity and rename things
INFO_FILE_RE = re.compile(r'.+_attempt_[0-9-]{19}\.txt')
STUD_ID_RE = re.compile(r'^Name:.+\((.+)\)$')
ORIG_FILE_RE = re.compile(r'^\tOriginal filename: (.+)$')
FILE_RE = re.compile(r'^\tFilename: (.+)$')


open_utf8 = partial(open, encoding='utf-8', errors='replace') # pylint: disable=C0103


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


def get_args(root):
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

    args = parser.parse_args()

    args.directory = os.path.join(root, args.directory)
    args.zipfile = os.path.join(args.directory, args.zipfile)
    args.resources = os.path.join(root, args.resources)
    args.commands = os.path.join(root, args.commands)
    args.correct_output = os.path.join(root, args.correct_output)

    return args


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


def run(args, run_file):
    """Compiles and runs code in temp directory."""

    stud_id = os.path.basename(os.getcwd())

    with open_utf8(GRADING_FILE.format(stud_id), 'w') as mfile:
        mfile.writelines([
            'Grading for {0}.\n\n'.format(stud_id),
            'Score: \n',
            'Grader: {0}\n'.format(os.getenv('GRADER', '')),
        ])

    run_setup_temp(args)
    cheat_check()
    output = run_commands(args, run_file)
    run_diff(args, output)

    if output:
        shutil.rmtree(TEMP_DIR)


def run_setup_temp(args):
    """Create temp directory and copy student and resource files into it."""

    # Going to run submission in temp subdirectory
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.mkdir(TEMP_DIR)

    # Copy default resources into temp directory
    for fname in os.listdir(args.resources):
        src = os.path.join(args.resources, fname)
        dst = os.path.join(TEMP_DIR, fname)
        shutil.copy(src, dst)

    # Copy student resources into temp directory
    fnames = (fname for fname in os.listdir('.') if os.path.isfile(fname))
    for fname in fnames:
        name, ext = os.path.splitext(fname)
        if name in ('Makefile') or ext in ('.c', '.h'):
            src = fname
            dst = os.path.join(TEMP_DIR, fname)
            shutil.copy(src, dst)


def cheat_check():
    """Find output calls in source files to check for obvious cheating."""

    stud_id = os.path.basename(os.getcwd())
    prints_file = open_utf8(PRINT_FILE.format(stud_id), 'w')

    fnames = (fname for fname in os.listdir('.') if fname.endswith('.c'))
    for fname in fnames:
        source_file = open_utf8(fname)

        lines = source_file.readlines()

        calls = find_output_calls(lines)
        prints_file.writelines(calls)

        source_file.close()


def run_commands(args, run_file):
    """Run commands using subprocess module."""

    stud_id = os.path.basename(os.getcwd())
    raw_file = open_utf8(OUTPUT_RAW_FILE.format(stud_id), 'w')

    with open_utf8(args.commands) as commands_file:
        commands = commands_file.readlines()

    os.chdir(TEMP_DIR)

    # Need to get absolute paths for binary files
    commands = glob_commands(commands)

    output = []
    for command in commands:
        try:
            out_bytes = check_output(command, stderr=STDOUT, timeout=2)
            out_str = str(out_bytes, encoding='utf-8', errors='replace')
            output.extend(out_str.splitlines(keepends=True))
        except SubprocessError as error:
            print('💀 {0}'.format(stud_id), file=run_file)
            print(str(error), file=raw_file)

            # pylint: disable=E1101
            if isinstance(error, CalledProcessError):
                message = str(error.output, encoding='utf-8', errors='replace')
                print(message, file=raw_file)

            os.chdir('..')
            return None

    print('✅ {0}'.format(stud_id), file=run_file)
    os.chdir('..')
    return output


def run_diff(args, output):
    """Create unified diff between student output and rubric."""

    if not output:
        return

    stud_id = os.path.basename(os.getcwd())

    raw_out_file = open_utf8(OUTPUT_RAW_FILE.format(stud_id), 'w')
    cond_out_file = open_utf8(OUTPUT_COND_FILE.format(stud_id), 'w')
    diff_file = open_utf8(DIFF_FILE.format(stud_id), 'w')

    raw_out_file.writelines(output)
    output = collapse_whitespace(output)
    cond_out_file.writelines(output)

    correct = get_correct_output(args)

    diff = unified_diff(correct, output, fromfile='correct', tofile='student')

    diff_file.writelines(diff)


def get_correct_output(args):
    """Get the correct output with spaces collapsed (simplifies diff)."""

    with open_utf8(args.correct_output) as cofile:
        output = cofile.readlines()
    output = collapse_whitespace(output)
    return output
    # with open_utf8(COND_CORR_FILE, 'w') as ccofile:
    #     ccofile.writelines(corr_out)

# pylint: disable=R0912, R0914, R0915
def main():
    """
    1. Unzip file from Blackboard
    2. Create student directories
    3. Rename files
    4. Run commands.txt
    """

    args = get_args(os.getcwd())

    directory = os.path.abspath(args.directory)

    os.chdir(directory)

    run_file = open_utf8(RUN_FILE.format(int(time.time())), 'w')

    # Just rerun for single student
    if args.regrade:
        stud_id = args.regrade
        os.chdir(os.path.join(SUBS_DIR, stud_id))
        run(args, run_file)
        return

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
        run(args, run_file)

        os.chdir(directory)

    shutil.rmtree(TEMP_DIR)


if __name__ == '__main__':
    main()
