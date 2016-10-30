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

    return parser.parse_args()


def condense_spaces(raw):
    parsed = []

    for line in raw:
        line = re.sub(r'\s+', ' ', line)
        line = re.sub(r'^\s?', '', line)
        line = re.sub(r'\s$', '\n', line)

        parsed.append(line)

    return parsed


def run():
    """Unzip file from Blackboard, create student directories, rename files, and run commands.txt for each."""

    args = process_args()

    work_path = os.path.abspath(args.directory)
    res_path = os.path.abspath(args.resources)
    cmd_file = os.path.abspath(args.commands)
    correct = open(args.output).readlines()
    correct = condense_spaces(correct)

    grader = args.grader

    os.chdir(work_path)
    archive = zipfile.ZipFile(args.zipfile, 'r')

    # Make top-level directories
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.mkdir(TEMP_DIR)
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

        # Copy student's files and default resources into temp directory
        # Look for print or write statements to check for cheating
        os.mkdir(os.path.join(work_path, TEMP_DIR, RUN_DIR))
        os.chdir(os.path.join(work_path, SUBS_DIR, student_id))
        print_file = open(PRINT_FILE.format(student_id), 'w')
        for file_name in os.listdir('.'):
            if file_name.endswith('.c') or file_name == 'Makefile':
                with open(file_name) as f:
                    print_file.writelines(print_check(f.readlines()))
                shutil.copy(file_name, os.path.join(work_path, TEMP_DIR, RUN_DIR))

        for res_file_name in os.listdir(res_path):
            shutil.copy(os.path.join(res_path, res_file_name), os.path.join(work_path, TEMP_DIR, RUN_DIR))

        # Run the student's submission in 'temp/run' and save the output in their abc123 directory
        run_submission(correct, cmd_file, grader, student_id, work_path)

        os.chdir(work_path)
        shutil.rmtree(os.path.join(TEMP_DIR, RUN_DIR))
        # End of submission running

    shutil.rmtree(TEMP_DIR)


def print_check(raw):
    matches = []

    for line in raw:
        match = re.match(r'.+(printf|write) *\(.+', line)
        if match:
            matches += line

    return matches


def run_submission(correct, cmd_file, grader, student_id, work_path):
    # Open output and grading text files
    os.chdir(os.path.join(work_path, SUBS_DIR, student_id))
    grading_file = open(GRADING_FILE.format(student_id), 'w')
    out_file = open(OUTPUT_FILE.format(student_id), 'w')
    diff_file = open(DIFF_FILE.format(student_id), 'w')

    print('Assignment 2 ({0})'.format(student_id), file=grading_file)
    os.chdir(os.path.join(work_path, TEMP_DIR, RUN_DIR))
    commands = glob_commands_txt(cmd_file)
    output = []
    success = True
    for cmd in commands:
        try:
            output += check_output(cmd, stderr=STDOUT, timeout=5, universal_newlines=True).splitlines(keepends=True)
        except (CalledProcessError, FileNotFoundError, TimeoutExpired) as err:
            print("* Doesn't compile, doesn't run, or has significant issues", file=grading_file)
            print("* Failed for command: {0}".format(' '.join(cmd)), file=grading_file)
            if isinstance(err, CalledProcessError):
                print(str(err.output), file=grading_file)
            if isinstance(err, TimeoutExpired):
                print("* Command timed out", file=grading_file)
            if isinstance(err, FileNotFoundError):
                print("* File not found", file=grading_file)
            success = False
            break

    if success:
        print(''.join(output), file=out_file)
        output = condense_spaces(output)
        diff_file.writelines(unified_diff(correct, output, fromfile='correct', tofile='student'))

    print('', file=grading_file)
    print('Score: ', file=grading_file)
    print('Grader: {0}'.format(grader), file=grading_file)


if __name__ == '__main__':
    run()
