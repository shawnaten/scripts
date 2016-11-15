#!/usr/bin/python3

"""Script to help automate grading programming assignments submitted to Blackboard.

Setup for UTSA CS 1713, Intro to Programming 2, which teaches simple C programming.
Takes a zipfile generated from the web interface and creates individual directories for students.
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

# REs to identity and rename things
INFO_FILE_RE = re.compile(r'.+_attempt_[0-9-]{19}\.txt')
STUDENT_ID_RE = re.compile(r'^Name:.+\((.+)\)$')
ORIG_FILE_RE = re.compile(r'^\tOriginal filename: (.+)$')
FILE_RE = re.compile(r'^\tFilename: (.+)$')


def glob_commands_txt(path):
    """Globs the tokens in commands.txt file. Use glob to handle wildcards without actually using a shell."""

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

    parser = argparse.ArgumentParser(description='Setup grading directories and run assignments for CS 1713.')

    parser.add_argument('grader', help='String to use for grader info.')

    parser.add_argument('-d', '--directory', default='.', help='The directory you want to grade in.')
    parser.add_argument('-z', '--zipfile', default="blackboard.zip", help='The zipfile from Blackboard.')
    parser.add_argument('-r', '--resources', default='resources',
                        help='Directory with the default resources needed to run the assignment.')
    parser.add_argument('-c', '--commands', default='commands.txt',
                        help='Text file with line separated commands to run.')
    parser.add_argument('-o', '--output', default='output.txt', help='File with correct output.')

    parser.add_argument('-R', '--regrade', help='File of Student IDs to regrade.', default=None)

    return parser.parse_args()


def condense_spaces(raw):
    parsed = []

    for line in raw:
        line = re.sub(r'\s+', ' ', line)
        line = re.sub(r'^\s?', '', line)
        line = re.sub(r'\s$', '\n', line)

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
    """Prepares a temp directory to run code in, globs the commands, compiles, runs, and generates output files."""

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
        shutil.copy(os.path.join(res_path, res_file_name), os.path.join(TEMP_DIR, res_file_name))

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
            output += check_output(cmd, stderr=STDOUT, timeout=5, universal_newlines=True).splitlines(keepends=True)
        except Exception as err:
            print("* Failed for command: {0}".format(' '.join(cmd)), file=grading_file)
            if isinstance(err, CalledProcessError):
                print(str(err.output), file=grading_file)
            elif isinstance(err, TimeoutExpired):
                print("* Command timed out", file=grading_file)
            elif isinstance(err, FileNotFoundError):
                print("* File not found", file=grading_file)
            else:
                print("* Didn't match expected exception types", file=grading_file)
            success = False
            break

    if success:
        print(''.join(output), file=out_file)
        output = condense_spaces(output)
        diff_file.writelines(unified_diff(correct, output, fromfile='correct', tofile='student'))

    print('', file=grading_file)
    print('Score: ', file=grading_file)
    print('Grader: {0}'.format(grader), file=grading_file)

    os.chdir('..')
    shutil.rmtree(TEMP_DIR)


def main():
    """Unzip file from Blackboard, create student directories, rename files, and run commands.txt for each."""

    args = process_args()

    work_path = os.path.abspath(args.directory)
    res_path = os.path.abspath(args.resources)
    cmd_file = os.path.abspath(args.commands)
    correct = open(args.output).readlines()
    correct = condense_spaces(correct)

    grader = args.grader
    regrade_file = args.regrade

    os.chdir(work_path)

    if regrade_file:
        regrade_file = open(regrade_file)
        for student_id in regrade_file.read().splitlines():
            if not os.path.exists(os.path.join(SUBS_DIR, student_id)):
                raise Exception("Student directory ({0}) does not exist".format(student_id))
            os.chdir(os.path.join(SUBS_DIR, student_id))
            run(correct, cmd_file, grader, student_id, res_path)
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

    # Traverse temp directory, looking for submission info file, then process each of those
    for raw_file_name in os.listdir(TEMP_DIR):
        re_match = INFO_FILE_RE.search(raw_file_name)

        if not re_match:
            continue

        # Process the info file which maps user actual submissions to Blackboard's ugly zipfile names
        with open(os.path.join(TEMP_DIR, raw_file_name)) as info_file:
            student_id = None
            orig_file_name = None

            for line in info_file.readlines():
                # Line with the student's name / ID
                re_match = STUDENT_ID_RE.search(line)
                if re_match:
                    student_id = re_match.group(1)
                    os.mkdir(os.path.join(SUBS_DIR, student_id))
                    os.rename(info_file.name, os.path.join(SUBS_DIR, student_id, INFO_FILE.format(student_id)))
                    continue

                # Line with an original filename (as the student submitted)
                re_match = ORIG_FILE_RE.search(line)
                if re_match:
                    orig_file_name = re_match.group(1)
                    continue

                # Line with the filename as it is in the zipfile, here we actually rename the files
                re_match = FILE_RE.search(line)
                if re_match:
                    raw_file_name = re_match.group(1)
                    os.rename(os.path.join(TEMP_DIR, raw_file_name), os.path.join(SUBS_DIR, student_id, orig_file_name))
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

        # Run the student's submission in 'temp/run' and save the output in their abc123 directory
        run(correct, cmd_file, grader, student_id, res_path)

        os.chdir(work_path)


if __name__ == '__main__':
    main()
