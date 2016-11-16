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
STUDENT_ID_RE = re.compile(r'^Name:.+\((.+)\)$')
ORIG_FILE_RE = re.compile(r'^\tOriginal filename: (.+)$')
FILE_RE = re.compile(r'^\tFilename: (.+)$')


def glob_commands_txt(path):
    """Globs the tokens in commands.txt without using a shell."""

    file = open(path)
    lines = file.readlines()

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


def process_args():
    """Process the command line args."""

    parser = argparse.ArgumentParser(
        description='Help automate grading for CS 1713.'
    )

    parser.add_argument('grader', help='String to use for grader info.')

    parser.add_argument('-d', '--directory', default='.',
                        help='The directory you want to grade in.')
    parser.add_argument('-z', '--zipfile', default="blackboard.zip",
                        help='The zipfile from Blackboard.')
    parser.add_argument('-r', '--resources', default='resources',
                        help='Directory with resources to compile assignment.')
    parser.add_argument('-c', '--commands', default='commands.txt',
                        help='Text file with line separated commands to run.')
    parser.add_argument('-o', '--output', default='output.txt',
                        help='File with correct output.')

    parser.add_argument('-R', '--regrade',
                        help='File of Student IDs to regrade.', default=None)

    return parser.parse_args()


def condense_spaces(raw):
    parsed = []

    for line in raw:
        line = re.sub(r'^\s+', '', line)
        line = re.sub(r'\s+$', '\n', line)
        line = re.sub(r'\s{2,}', ' ', line)

        if line != '':
            parsed.append(line)

    return parsed


def print_check(raw):
    matches = []

    for line in raw:
        match = re.match(r'.+(printf|write) *\(.+', line)
        if match:
            matches += line

    return matches


def regrade(correct, cmd_file, grader, student_id, res_path):
    files = []
    files += OUTPUT_FILE.format(student_id)
    files += GRADING_FILE.format(student_id)
    files += DIFF_FILE.format(student_id)
    files += GRADING_FILE.format(student_id)
    for file in files:
        if os.path.exists(file):
            os.remove(file)

    os.chdir(os.path.join(SUBS_DIR, student_id))
    run(correct, cmd_file, grader, student_id, res_path)


def run(correct, cmd_file, grader, student_id, res_path):
    """Compiles and runs code in temp directory."""

    # Going to run submission in temp subdirectory
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.mkdir(TEMP_DIR)

    # Open analysis files
    grading_file = open(GRADING_FILE.format(student_id), 'w')
    out_file = open(OUTPUT_FILE.format(student_id), 'w')
    diff_file = open(DIFF_FILE.format(student_id), 'w')
    print_file = open(PRINT_FILE.format(student_id), 'w')

    # Copy default resources into temp directory
    for res_file_name in os.listdir(res_path):
        shutil.copy(
            os.path.join(res_path, res_file_name),
            os.path.join(TEMP_DIR, res_file_name)
        )

    # Copy student resources into temp directory
    files = (file for file in os.listdir('.') if os.path.isfile(file))
    for file in files:
        shutil.copy(file, os.path.join(TEMP_DIR, file))
        if file.endswith('.c'):
            with open(file) as f:
                try:
                    print_file.writelines(print_check(f.readlines()))
                except UnicodeDecodeError as err:
                    print("* Failed to parse source code", file=grading_file)
                    return

    os.chdir(TEMP_DIR)

    # Need to get absolute path for binary file
    commands = glob_commands_txt(cmd_file)

    print('Assignment 2 ({0})'.format(student_id), file=grading_file)

    output = []
    success = True
    for cmd in commands:
        try:
            cmd_output = check_output(cmd, stderr=STDOUT, timeout=5,
                                      universal_newlines=True)
            output += cmd_output.splitlines(keepends=True)
        except Exception as err:
            print("* Failed for command: {0}".format(' '.join(cmd)),
                  file=grading_file)
            if isinstance(err, CalledProcessError):
                print(str(err.output), file=grading_file)
            elif isinstance(err, TimeoutExpired):
                print("* Command timed out", file=grading_file)
            elif isinstance(err, FileNotFoundError):
                print("* File not found", file=grading_file)
            else:
                print("* Didn't match expected exception types",
                      file=grading_file)
            success = False
            break

    if success:
        output = condense_spaces(output)
        out_file.writelines(output)
        diff = unified_diff(
            correct, output,
            fromfile='correct', tofile='student'
        )
        diff_file.writelines(diff)

    print('', file=grading_file)
    print('Score: ', file=grading_file)
    print('Grader: {0}'.format(grader), file=grading_file)

    os.chdir('..')
    shutil.rmtree(TEMP_DIR)


def main():
    """
    1. Unzip file from Blackboard
    2. Create student directories
    3. Rename files
    4. Run commands.txt
    """

    args = process_args()

    work_path = os.path.abspath(args.directory)
    res_path = os.path.abspath(args.resources)
    cmd_file = os.path.abspath(args.commands)

    with open(args.output) as f:
        corr_out = f.readlines()
        corr_out = condense_spaces(corr_out)

    with open(COND_CORR_FILE, 'w') as f:
        f.writelines(corr_out)

    grader = args.grader
    regrade_file = args.regrade

    os.chdir(work_path)

    if regrade_file:
        regrade_file = open(regrade_file)
        for student_id in regrade_file.read().splitlines():
            if not os.path.exists(os.path.join(SUBS_DIR, student_id)):
                raise Exception(
                    "Student directory ({0}) does not exist".format(student_id)
                )
            os.chdir(os.path.join(SUBS_DIR, student_id))
            run(corr_out, cmd_file, grader, student_id, res_path)
            os.chdir(work_path)
        return

    archive = zipfile.ZipFile(args.zipfile, 'r')

    # Make top-level directories
    if os.path.exists(SUBS_DIR):
        shutil.rmtree(SUBS_DIR)
    os.mkdir(SUBS_DIR)

    # Extract the zipfile to temp directory
    archive.extractall(TEMP_DIR)
    archive.close()

    # Traverse temp directory, looking for submission info files to process
    for raw_file_name in os.listdir(TEMP_DIR):
        re_match = INFO_FILE_RE.search(raw_file_name)

        if not re_match:
            continue

        # Process the info file
        # Info file maps actual submissions to Blackboard's ugly zipfile names
        with open(
            os.path.join(TEMP_DIR, raw_file_name),
            encoding='utf-8'
        ) as info_file:
            student_id = None
            orig_file_name = None

            for line in info_file.readlines():
                # Line with the student's name / ID
                re_match = STUDENT_ID_RE.search(line)
                if re_match:
                    student_id = re_match.group(1)
                    os.mkdir(os.path.join(SUBS_DIR, student_id))
                    os.rename(info_file.name, os.path.join(
                        SUBS_DIR, student_id, INFO_FILE.format(student_id)))
                    continue

                # Line with an original filename (as the student submitted)
                re_match = ORIG_FILE_RE.search(line)
                if re_match:
                    orig_file_name = re_match.group(1)
                    continue

                # Line with the filename as it is in the zipfile
                re_match = FILE_RE.search(line)
                if re_match:
                    raw_file_name = re_match.group(1)
                    os.rename(
                        os.path.join(TEMP_DIR, raw_file_name),
                        os.path.join(SUBS_DIR, student_id, orig_file_name)
                    )
                    continue

        # Uncompress archive files if any
        os.chdir(os.path.join(SUBS_DIR, student_id))
        for file_name in os.listdir('.'):
            name, extension = os.path.splitext(file_name)

            if extension in ('.zip', '.tar', '.gz'):
                if extension == '.zip':
                    archive = zipfile.ZipFile(file_name, 'r')
                elif extension == '.tar':
                    archive = tarfile.open(file_name, 'r')
                elif extension == '.gz':
                    archive = tarfile.open(file_name, 'r:gz')

                archive.extractall()
                archive.close()
                os.remove(file_name)

                if os.path.isdir(name):
                    for unzip_file in os.listdir(name):
                        os.rename(os.path.join(name, unzip_file), unzip_file)
                    shutil.rmtree(name)

        # Run submission in 'temp/run'
        run(corr_out, cmd_file, grader, student_id, res_path)

        os.chdir(work_path)


if __name__ == '__main__':
    main()
