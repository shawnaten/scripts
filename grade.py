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

from subprocess import check_output, STDOUT, CalledProcessError, TimeoutExpired

# Various directories for output
TEMP_DIR = 'temp'
SUBS_DIR = 'submissions'
RUN_DIR = 'run'

# Name strings for student files
INFO_FILE = '{0}.info.txt'  # Blackboard info file
OUTPUT_FILE = '{0}.out.txt'
GRADING_FILE = '{0}.grading.txt'

# REs to identity and rename things
INFO_FILE_RE = re.compile(r'.+_attempt_[0-9-]{19}\.txt')
STUDENT_ID_RE = re.compile(r'^Name:.+\((.+)\)$')
ORIG_FILE_RE = re.compile(r'^\tOriginal filename: (.+)$')
FILE_RE = re.compile(r'^\tFilename: (.+)$')


class ReadableDirectory(argparse.Action):
    """Action class for ArgumentParser to validate a readable directory from the command line."""

    def __call__(self, parser, namespace, values, option_string=None):
        prospective_dir = values

        if not os.path.isdir(prospective_dir):
            raise argparse.ArgumentTypeError('{0} is not a valid path'.format(prospective_dir))

        if os.access(prospective_dir, os.R_OK):
            setattr(namespace, self.dest, prospective_dir)
        else:
            raise argparse.ArgumentTypeError('{0} is not a readable dir'.format(prospective_dir))


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

    parser.add_argument('assignment', help='The name of the assignment.')
    parser.add_argument('grader', help='The name of the grader.')

    parser.add_argument('-d', '--directory', default='.', help='The directory you want to grade in.')
    parser.add_argument('-z', '--zipfile', default="blackboard.zip", help='The zipfile from Blackboard.')
    parser.add_argument('-r', '--resources', default='resources',
                        help='The directory with the default resources needed to run the assignment.')
    parser.add_argument('-c', '--commands', default='commands.txt',
                        help='File with commands to run for each submission, separated by newlines.')

    return parser.parse_args()


def run():
    """Unzip file from Blackboard, create student directories, rename files, and run commands.txt for each."""

    args = process_args()

    work_path = os.path.abspath(args.directory)
    res_path = os.path.abspath(args.resources)
    commands_path = os.path.abspath(args.commands)

    os.chdir(work_path)
    archive = zipfile.ZipFile(args.zipfile, 'r')
    assignment = args.assignment
    grader = args.grader

    # Make top-level directories
    if os.path.exists(TEMP_DIR):
        raise Exception('{0} directory already exists'.format(TEMP_DIR))
    os.mkdir(TEMP_DIR)
    if os.path.exists(SUBS_DIR):
        raise Exception('{0} directory already exists'.format(SUBS_DIR))
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
                print('Extracting archive ({0}): {1}'.format(student_id, file_name))

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

        # Move C and Makefile's into a temp directory to run
        os.mkdir(os.path.join(work_path, TEMP_DIR, RUN_DIR))
        for file_name in os.listdir('.'):
            if file_name.endswith('.c') or file_name == 'Makefile':
                shutil.copy(file_name, os.path.join(work_path, TEMP_DIR, RUN_DIR))

        # Generate a template grading.txt file
        grading_file = open(os.path.join(GRADING_FILE.format(student_id)), 'w')
        grading_file.write('Grading for {0} ({1}).\n\n'.format(assignment, student_id))

        # Run the student's submission in 'temp/run' and save the output in their abc123 directory
        os.chdir(os.path.join(work_path, TEMP_DIR, RUN_DIR))
        for res_file_name in os.listdir(res_path):
            shutil.copy(os.path.join(res_path, res_file_name), '.')

        commands = glob_commands_txt(commands_path)
        output = []
        for cmd in commands:
            try:
                output.append(str(check_output(cmd, stderr=STDOUT, timeout=10), 'utf-8'))
            except (CalledProcessError, FileNotFoundError, TimeoutExpired) as err:
                print('Compile or run error ({0}):  {1}'.format(student_id, cmd))
                grading_file.write('* Compile or run error: {0}\n'.format(cmd))
                output.append('* Compile or run error: {0}\n'.format(cmd))
                if isinstance(err, CalledProcessError):
                    output.append(str(err.output, 'utf-8'))
                if isinstance(err, TimeoutExpired):
                    grading_file.write('* Command timed out\n')
                    output.append('* Command timed out\n')
                if isinstance(err, FileNotFoundError):
                    grading_file.write('* File not found\n')
                    output.append('* File not found\n')

        output_file = open(os.path.join(work_path, SUBS_DIR, student_id, OUTPUT_FILE.format(student_id)), 'w')
        output_file.writelines(output)

        grading_file.write('\n')
        grading_file.write('Score: \n')
        grading_file.write('Grader: {0}\n'.format(grader))

        grading_file.close()
        output_file.close()
        os.chdir(work_path)
        shutil.rmtree(os.path.join(TEMP_DIR, RUN_DIR))
        # End of submission running

    shutil.rmtree(TEMP_DIR)


if __name__ == '__main__':
    run()
