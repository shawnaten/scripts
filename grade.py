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
import zipfile

from subprocess import check_output, STDOUT, CalledProcessError

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

    parser.add_argument('zipfile', type=argparse.FileType('r'), help='The zipfile from Blackboard.')
    parser.add_argument('assignment', help='The name of the assignment.')
    parser.add_argument('grader', help='The name of the grader.')

    parser.add_argument('-d', '--directory', action=ReadableDirectory, default='.',
                        help='The directory you want to grade in.')
    parser.add_argument('-r', '--resources', action=ReadableDirectory, default='resources',
                        help='The directory with the default resources needed to run the assignment.')
    parser.add_argument('-c', '--commands', default='commands.txt', type=argparse.FileType('r'),
                        help='File with commands to run for each submission, separated by newlines.')

    return parser.parse_args()


def run():
    """Unzip file from Blackboard, create student directories, rename files, and run commands.txt for each."""

    args = process_args()

    work_path = os.path.abspath(args.directory)
    res_path = os.path.abspath(args.resources)
    zip_file = zipfile.ZipFile(args.zipfile.name, 'r')
    assignment = args.assignment
    grader = args.grader
    commands_path = os.path.abspath(args.commands.name)

    os.chdir(work_path)

    # Make top-level directories
    if os.path.exists(TEMP_DIR):
        raise Exception('{0} directory already exists'.format(TEMP_DIR))
    os.mkdir(TEMP_DIR)
    if os.path.exists(SUBS_DIR):
        raise Exception('{0} directory already exists'.format(SUBS_DIR))
    os.mkdir(SUBS_DIR)

    # Extract the zipfile to temp directory
    zip_file.extractall(TEMP_DIR)
    zip_file.close()

    # Traverse temp directory, looking for submission info file, then process each of those
    for file_name in os.listdir(TEMP_DIR):
        re_match = INFO_FILE_RE.search(file_name)

        if not re_match:
            continue

        # Process the info file which maps user actual submissions to Blackboard's ugly zipfile names
        with open(os.path.join(TEMP_DIR, file_name)) as info_file:
            for line in info_file.readlines():
                # Line with the student's name / ID
                re_match = STUDENT_ID_RE.search(line)
                if re_match:
                    stud_id = re_match.group(1)
                    os.mkdir(os.path.join(SUBS_DIR, stud_id))
                    os.mkdir(os.path.join(TEMP_DIR, RUN_DIR))
                    os.rename(info_file.name, os.path.join(SUBS_DIR, stud_id, INFO_FILE.format(stud_id)))
                    continue

                # Line with an original filename (as the student submitted)
                re_match = ORIG_FILE_RE.search(line)
                if re_match:
                    orig_file_name = re_match.group(1)
                    continue

                # Line with the filename as it is in the zipfile, here we actually rename the files
                re_match = FILE_RE.search(line)
                if re_match:
                    file_name = re_match.group(1)
                    if stud_id is None or orig_file_name is None:
                        raise Exception('Something is wrong with the info file: {0)'.format(info_file))
                    os.rename(os.path.join(TEMP_DIR, file_name), os.path.join(SUBS_DIR, stud_id, orig_file_name))
                    # Move the C or Makefile's into a directory to run
                    if orig_file_name.endswith('.c') or orig_file_name == 'Makefile':
                        shutil.copy(os.path.join(SUBS_DIR, stud_id, orig_file_name), os.path.join(TEMP_DIR, RUN_DIR))
                    continue

        # Generate a template grading.txt file
        with open(os.path.join(SUBS_DIR, stud_id, GRADING_FILE.format(stud_id)), 'w') as grading_file:
            grading_file.writelines([
                'Grading for {0} ({1}).\n'.format(assignment, stud_id),
                '\n',
                '*\n',
                '\n',
                'Score: \n',
                'Grader: {0}\n'.format(grader),
            ])

        # Run the student's submission in 'temp/run' and save the output in their abc123 directory
        os.chdir(os.path.join(TEMP_DIR, RUN_DIR))
        for res_file_name in os.listdir(res_path):
            shutil.copy(os.path.join(res_path, res_file_name), '.')

        commands = glob_commands_txt(commands_path)
        output = []
        for cmd in commands:
            try:
                output.append(str(check_output(cmd, stderr=STDOUT, timeout=10), 'utf-8'))
            except CalledProcessError as err:
                output.append(str(err.output, 'utf-8'))
            except FileNotFoundError as err:
                output.append('File not found: {0}'.format(err))

        output_file = open(os.path.join(work_path, SUBS_DIR, stud_id, OUTPUT_FILE.format(stud_id)), 'w')

        output_file.writelines(output)

        os.chdir(work_path)
        shutil.rmtree(os.path.join(TEMP_DIR, RUN_DIR))
        # End of submission running

    shutil.rmtree(TEMP_DIR)


if __name__ == '__main__':
    run()
