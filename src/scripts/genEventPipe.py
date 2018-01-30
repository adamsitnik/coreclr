﻿from __future__ import print_function
from genEventing import *
from genLttngProvider import *
import os
import xml.dom.minidom as DOM
from utilities import open_for_update

stdprolog_cpp = """// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.
// See the LICENSE file in the project root for more information.

/******************************************************************

DO NOT MODIFY. AUTOGENERATED FILE.
This file is generated using the logic from <root>/src/scripts/genEventPipe.py

******************************************************************/

"""

stdprolog_cmake = """#
#
#******************************************************************

#DO NOT MODIFY. AUTOGENERATED FILE.
#This file is generated using the logic from <root>/src/scripts/genEventPipe.py

#******************************************************************

"""

eventpipe_dirname = "eventpipe"

def generateMethodSignatureEnabled(eventName):
    return "BOOL EventPipeEventEnabled%s()" % (eventName,)

def generateMethodSignatureWrite(eventName, template, extern):
    sig_pieces = []

    if extern: sig_pieces.append('extern "C" ')
    sig_pieces.append("ULONG EventPipeWriteEvent")
    sig_pieces.append(eventName)
    sig_pieces.append("(")

    if template:
        sig_pieces.append("\n")
        fnSig = template.signature
        for paramName in fnSig.paramlist:
            fnparam = fnSig.getParam(paramName)
            wintypeName = fnparam.winType
            typewName = palDataTypeMapping[wintypeName]
            winCount = fnparam.count
            countw = palDataTypeMapping[winCount]

            if paramName in template.structs:
                sig_pieces.append(
                    "%sint %s_ElementSize,\n" %
                    (lindent, paramName))

            sig_pieces.append(lindent)
            sig_pieces.append(typewName)
            if countw != " ":
                sig_pieces.append(countw)

            sig_pieces.append(" ")
            sig_pieces.append(fnparam.name)
            sig_pieces.append(",\n")

        if len(sig_pieces) > 0:
            del sig_pieces[-1]

    sig_pieces.append(")")
    return ''.join(sig_pieces)

def generateClrEventPipeWriteEventsImpl(
        providerName, eventNodes, allTemplates, extern):
    providerPrettyName = providerName.replace("Windows-", '')
    providerPrettyName = providerPrettyName.replace("Microsoft-", '')
    providerPrettyName = providerPrettyName.replace('-', '_')
    WriteEventImpl = []

    # EventPipeEvent declaration
    for eventNode in eventNodes:
        eventName = eventNode.getAttribute('symbol')
        WriteEventImpl.append(
            "EventPipeEvent *EventPipeEvent" +
            eventName +
            " = nullptr;\n")

    for eventNode in eventNodes:
        eventName = eventNode.getAttribute('symbol')
        templateName = eventNode.getAttribute('template')

        # generate EventPipeEventEnabled function
        eventEnabledImpl = generateMethodSignatureEnabled(eventName) + """
{
    return EventPipeEvent%s->IsEnabled();
}

""" % eventName
        WriteEventImpl.append(eventEnabledImpl)

        # generate EventPipeWriteEvent function
        fnptype = []

        if templateName:
            template = allTemplates[templateName]
        else:
            template = None

        fnptype.append(generateMethodSignatureWrite(eventName, template, extern))
        fnptype.append("\n{\n")
        checking = """    if (!EventPipeEventEnabled%s())
        return ERROR_SUCCESS;
""" % (eventName)

        fnptype.append(checking)

        WriteEventImpl.extend(fnptype)

        if template:
            body = generateWriteEventBody(template, providerName, eventName)
            WriteEventImpl.append(body)
        else:
            WriteEventImpl.append(
                "    EventPipe::WriteEvent(*EventPipeEvent" +
                eventName +
                ", (BYTE*) nullptr, 0);\n")

        WriteEventImpl.append("\n    return ERROR_SUCCESS;\n}\n\n")

    # EventPipeProvider and EventPipeEvent initialization
    callbackName = 'EventPipeEtwCallback' + providerPrettyName
    if extern: WriteEventImpl.append('extern "C" ')
    WriteEventImpl.append(
        "void Init" +
        providerPrettyName +
        "()\n{\n")
    WriteEventImpl.append(
        "    EventPipeProvider" +
        providerPrettyName +
        " = EventPipe::CreateProvider(SL(" +
        providerPrettyName +
        "Name), " + callbackName + ");\n")
    for eventNode in eventNodes:
        eventName = eventNode.getAttribute('symbol')
        templateName = eventNode.getAttribute('template')
        eventKeywords = eventNode.getAttribute('keywords')
        eventKeywordsMask = generateEventKeywords(eventKeywords)
        eventValue = eventNode.getAttribute('value')
        eventVersion = eventNode.getAttribute('version')
        eventLevel = eventNode.getAttribute('level')
        eventLevel = eventLevel.replace("win:", "EventPipeEventLevel::")
        taskName = eventNode.getAttribute('task')

        initEvent = """    EventPipeEvent%s = EventPipeProvider%s->AddEvent(%s,%s,%s,%s);
""" % (eventName, providerPrettyName, eventValue, eventKeywordsMask, eventVersion, eventLevel)

        WriteEventImpl.append(initEvent)
    WriteEventImpl.append("}")

    return ''.join(WriteEventImpl)


def generateWriteEventBody(template, providerName, eventName):
    header = """
    char stackBuffer[%s];
    char *buffer = stackBuffer;
    size_t offset = 0;
    size_t size = %s;
    bool fixedBuffer = true;

    bool success = true;
""" % (template.estimated_size, template.estimated_size)

    fnSig = template.signature
    pack_list = []
    for paramName in fnSig.paramlist:
        parameter = fnSig.getParam(paramName)

        if paramName in template.structs:
            size = "(int)%s_ElementSize * (int)%s" % (
                paramName, parameter.prop)
            if template.name in specialCaseSizes and paramName in specialCaseSizes[template.name]:
                size = "(int)(%s)" % specialCaseSizes[template.name][paramName]
            pack_list.append(
                "    success &= WriteToBuffer((const BYTE *)%s, %s, buffer, offset, size, fixedBuffer);" %
                (paramName, size))
        elif paramName in template.arrays:
            size = "sizeof(%s) * (int)%s" % (
                lttngDataTypeMapping[parameter.winType],
                parameter.prop)
            if template.name in specialCaseSizes and paramName in specialCaseSizes[template.name]:
                size = "(int)(%s)" % specialCaseSizes[template.name][paramName]
            pack_list.append(
                "    success &= WriteToBuffer((const BYTE *)%s, %s, buffer, offset, size, fixedBuffer);" %
                (paramName, size))
        elif parameter.winType == "win:GUID":
            pack_list.append(
                "    success &= WriteToBuffer(*%s, buffer, offset, size, fixedBuffer);" %
                (parameter.name,))
        else:
            pack_list.append(
                "    success &= WriteToBuffer(%s, buffer, offset, size, fixedBuffer);" %
                (parameter.name,))

    code = "\n".join(pack_list) + "\n\n"

    checking = """    if (!success)
    {
        if (!fixedBuffer)
            delete[] buffer;
        return ERROR_WRITE_FAULT;
    }\n\n"""

    body = "    EventPipe::WriteEvent(*EventPipeEvent" + \
        eventName + ", (BYTE *)buffer, (unsigned int)offset);\n"

    footer = """
    if (!fixedBuffer)
        delete[] buffer;
"""

    return header + code + checking + body + footer


keywordMap = {}

def generateEventKeywords(eventKeywords):
    mask = 0
    # split keywords if there are multiple
    allKeywords = eventKeywords.split()

    for singleKeyword in allKeywords:
        mask = mask | keywordMap[singleKeyword]

    return mask


def generateEventPipeCmakeFile(etwmanifest, eventpipe_directory, extern):
    tree = DOM.parse(etwmanifest)

    with open_for_update(os.path.join(eventpipe_directory, "CMakeLists.txt")) as cmake_file:
        cmake_file.write(stdprolog_cmake)
        cmake_file.write("cmake_minimum_required(VERSION 2.8.12.2)\n")
        if extern: cmake_file.write("\nproject(eventpipe)\n")
        cmake_file.write("""

set(CMAKE_INCLUDE_CURRENT_DIR ON)
include_directories(${CLR_DIR}/src/vm)

""")
        if extern: cmake_file.write("add_library")
        else: cmake_file.write("add_library_clr")
        cmake_file.write("""(eventpipe
    STATIC\n""")

        for providerNode in tree.getElementsByTagName('provider'):
            providerName = providerNode.getAttribute('name')
            providerName = providerName.replace("Windows-", '')
            providerName = providerName.replace("Microsoft-", '')

            providerName_File = providerName.replace('-', '')
            providerName_File = providerName_File.lower()

            cmake_file.write('    "%s/%s.cpp"\n' % (eventpipe_dirname, providerName_File))
        cmake_file.write('    "%s/eventpipehelpers.cpp"\n)' % (eventpipe_dirname,))
        if extern: cmake_file.write("""

# Install the static eventpipe library
install(TARGETS eventpipe DESTINATION lib)
""")

def generateEventPipeHelperFile(etwmanifest, eventpipe_directory, extern):
    with open_for_update(os.path.join(eventpipe_directory, "eventpipehelpers.cpp")) as helper:
        helper.write(stdprolog_cpp)
        helper.write("""
#include "common.h"
#include <stdlib.h>
#include <string.h>

#ifndef FEATURE_PAL
#include <windef.h>
#include <crtdbg.h>
#else
#include "pal.h"
#endif //FEATURE_PAL

bool ResizeBuffer(char *&buffer, size_t& size, size_t currLen, size_t newSize, bool &fixedBuffer)
{
    newSize = (size_t)(newSize * 1.5);
    _ASSERTE(newSize > size); // check for overflow

    if (newSize < 32)
        newSize = 32;

    char *newBuffer = new (nothrow) char[newSize];

    if (newBuffer == NULL)
        return false;

    memcpy(newBuffer, buffer, currLen);

    if (!fixedBuffer)
        delete[] buffer;

    buffer = newBuffer;
    size = newSize;
    fixedBuffer = false;

    return true;
}

bool WriteToBuffer(const BYTE *src, size_t len, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer)
{
    if(!src) return true;
    if (offset + len > size)
    {
        if (!ResizeBuffer(buffer, size, offset, size + len, fixedBuffer))
            return false;
    }

    memcpy(buffer + offset, src, len);
    offset += len;
    return true;
}

bool WriteToBuffer(PCWSTR str, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer)
{
    if(!str) return true;
    size_t byteCount = (wcslen(str) + 1) * sizeof(*str);

    if (offset + byteCount > size)
    {
        if (!ResizeBuffer(buffer, size, offset, size + byteCount, fixedBuffer))
            return false;
    }

    memcpy(buffer + offset, str, byteCount);
    offset += byteCount;
    return true;
}

bool WriteToBuffer(const char *str, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer)
{
    if(!str) return true;
    size_t len = strlen(str) + 1;
    if (offset + len > size)
    {
        if (!ResizeBuffer(buffer, size, offset, size + len, fixedBuffer))
            return false;
    }

    memcpy(buffer + offset, str, len);
    offset += len;
    return true;
}

""")

        tree = DOM.parse(etwmanifest)

        for providerNode in tree.getElementsByTagName('provider'):
            providerName = providerNode.getAttribute('name')
            providerPrettyName = providerName.replace("Windows-", '')
            providerPrettyName = providerPrettyName.replace("Microsoft-", '')
            providerPrettyName = providerPrettyName.replace('-', '_')
            if extern: helper.write(
                'extern "C" '
            )
            helper.write(
                "void Init" +
                providerPrettyName +
                "();\n\n")

        if extern: helper.write(
            'extern "C" '
        )
        helper.write("void InitProvidersAndEvents()\n{\n")
        for providerNode in tree.getElementsByTagName('provider'):
            providerName = providerNode.getAttribute('name')
            providerPrettyName = providerName.replace("Windows-", '')
            providerPrettyName = providerPrettyName.replace("Microsoft-", '')
            providerPrettyName = providerPrettyName.replace('-', '_')
            helper.write("    Init" + providerPrettyName + "();\n")
        helper.write("}")

    helper.close()

def generateEventPipeImplFiles(
        etwmanifest, eventpipe_directory, extern):
    tree = DOM.parse(etwmanifest)

    # Find the src directory starting with the assumption that
    # A) It is named 'src'
    # B) This script lives in it
    src_dirname = os.path.dirname(__file__)
    while os.path.basename(src_dirname) != "src":
        src_dirname = os.path.dirname(src_dirname)

        if os.path.basename(src_dirname) == "":
            raise IOError("Could not find the Core CLR 'src' directory")

    for providerNode in tree.getElementsByTagName('provider'):
        providerName = providerNode.getAttribute('name')

        providerPrettyName = providerName.replace("Windows-", '')
        providerPrettyName = providerPrettyName.replace("Microsoft-", '')
        providerName_File = providerPrettyName.replace('-', '')
        providerName_File = providerName_File.lower()
        providerPrettyName = providerPrettyName.replace('-', '_')
        eventpipefile = os.path.join(eventpipe_directory, providerName_File + ".cpp")
        with open_for_update(eventpipefile) as eventpipeImpl:
            eventpipeImpl.write(stdprolog_cpp)

            header = """
#include "{root:s}/vm/common.h"
#include "{root:s}/vm/eventpipeprovider.h"
#include "{root:s}/vm/eventpipeevent.h"
#include "{root:s}/vm/eventpipe.h"

#if defined(FEATURE_PAL)
#define wcslen PAL_wcslen
#endif

bool ResizeBuffer(char *&buffer, size_t& size, size_t currLen, size_t newSize, bool &fixedBuffer);
bool WriteToBuffer(PCWSTR str, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer);
bool WriteToBuffer(const char *str, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer);
bool WriteToBuffer(const BYTE *src, size_t len, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer);

template <typename T>
bool WriteToBuffer(const T &value, char *&buffer, size_t& offset, size_t& size, bool &fixedBuffer)
{{
    if (sizeof(T) + offset > size)
    {{
        if (!ResizeBuffer(buffer, size, offset, size + sizeof(T), fixedBuffer))
            return false;
    }}

    *(T *)(buffer + offset) = value;
    offset += sizeof(T);
    return true;
}}

""".format(root=src_dirname.replace('\\', '/'))

            eventpipeImpl.write(header)
            eventpipeImpl.write(
                "const WCHAR* %sName = W(\"%s\");\n" % (
                    providerPrettyName,
                    providerName
                )
            )
            eventpipeImpl.write(
                "EventPipeProvider *EventPipeProvider%s = nullptr;\n" % (
                    providerPrettyName,
                )
            )
            templateNodes = providerNode.getElementsByTagName('template')
            allTemplates = parseTemplateNodes(templateNodes)
            eventNodes = providerNode.getElementsByTagName('event')
            eventpipeImpl.write(
                generateClrEventPipeWriteEventsImpl(
                    providerName,
                    eventNodes,
                    allTemplates,
                    extern) + "\n")


def generateEventPipeFiles(
        etwmanifest, intermediate, extern):
    eventpipe_directory = os.path.join(intermediate, eventpipe_dirname)
    tree = DOM.parse(etwmanifest)

    if not os.path.exists(eventpipe_directory):
        os.makedirs(eventpipe_directory)

    # generate CMake file
    generateEventPipeCmakeFile(etwmanifest, intermediate, extern)

    # generate helper file
    generateEventPipeHelperFile(etwmanifest, eventpipe_directory, extern)

    # generate all keywords
    for keywordNode in tree.getElementsByTagName('keyword'):
        keywordName = keywordNode.getAttribute('name')
        keywordMask = keywordNode.getAttribute('mask')
        keywordMap[keywordName] = int(keywordMask, 0)

    # generate .cpp file for each provider
    generateEventPipeImplFiles(
        etwmanifest,
        eventpipe_directory,
        extern
    )

import argparse
import sys

def main(argv):

    # parse the command line
    parser = argparse.ArgumentParser(
        description="Generates the Code required to instrument eventpipe logging mechanism")

    required = parser.add_argument_group('required arguments')
    required.add_argument('--man', type=str, required=True,
                          help='full path to manifest containig the description of events')
    required.add_argument('--intermediate', type=str, required=True,
                          help='full path to eventprovider  intermediate directory')
    required.add_argument('--nonextern', action='store_true',
                          help='if specified, will generate files to be compiled into the CLR rather than extern' )
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print('Unknown argument(s): ', ', '.join(unknown))
        return 1

    sClrEtwAllMan = args.man
    intermediate = args.intermediate
    extern = not args.nonextern

    generateEventPipeFiles(sClrEtwAllMan, intermediate, extern)

if __name__ == '__main__':
    return_code = main(sys.argv[1:])
    sys.exit(return_code)
