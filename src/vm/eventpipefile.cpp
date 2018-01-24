// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.
// See the LICENSE file in the project root for more information.

#include "common.h"
#include "eventpipebuffer.h"
#include "eventpipeconfiguration.h"
#include "eventpipefile.h"
#include "sampleprofiler.h"

#ifdef FEATURE_PERFTRACING

EventPipeFile::EventPipeFile(
    SString &outputFilePath
#ifdef _DEBUG
    ,
    bool lockOnWrite
#endif // _DEBUG
)
{
    CONTRACTL
    {
        THROWS;
        GC_TRIGGERS;
        MODE_ANY;
    }
    CONTRACTL_END;

    SetObjectVersion(3);
    SetMinReaderVersion(0);

#ifdef _DEBUG
    m_lockOnWrite = lockOnWrite;
#endif // _DEBUG

    // File start time information.
    GetSystemTime(&m_fileOpenSystemTime);
    QueryPerformanceCounter(&m_fileOpenTimeStamp);
    QueryPerformanceFrequency(&m_timeStampFrequency);

    m_pointerSize = TARGET_POINTER_SIZE;

    m_currentProcessId = GetCurrentProcessId();

    SYSTEM_INFO sysinfo = {};
    GetSystemInfo(&sysinfo);
    m_numberOfProcessors = sysinfo.dwNumberOfProcessors;

    m_samplingRateInNs = SampleProfiler::GetSamplingRate();

    m_pSerializer = new FastSerializer(outputFilePath); // it creates the file stream and writes the header
    m_serializationLock.Init(LOCK_TYPE_DEFAULT);
    m_pMetadataLabels = new MapSHashWithRemove<EventPipeEvent*, StreamLabel>();

    m_pSerializer->WriteObject(this); // this is the first object in the file
}

EventPipeFile::~EventPipeFile()
{
    CONTRACTL
    {
        NOTHROW;
        GC_TRIGGERS;
        MODE_ANY;
    }
    CONTRACTL_END;

    // Close the serializer.
    if(m_pSerializer != NULL)
    {
        delete(m_pSerializer);
        m_pSerializer = NULL;
    }
}

void EventPipeFile::WriteEvent(EventPipeEventInstance &instance)
{
    CONTRACTL
    {
        THROWS;
        GC_NOTRIGGER;
        MODE_ANY;
    }
    CONTRACTL_END;

#ifdef _DEBUG
    if(m_lockOnWrite)
    {
        // Take the serialization lock.
        // This is used for synchronous file writes.
        // The circular buffer path only writes from one thread.
        SpinLockHolder _slh(&m_serializationLock);
    }
#endif // _DEBUG

    // Check to see if we've seen this event type before.
    // If not, then write the event metadata to the event stream first.
    StreamLabel metadataLabel = GetMetadataLabel(*instance.GetEvent());
    if(metadataLabel == 0)
    {
        EventPipeEventInstance* pMetadataInstance = EventPipe::GetConfiguration()->BuildEventMetadataEvent(instance);

        metadataLabel = m_pSerializer->GetStreamLabel();
        pMetadataInstance->FastSerialize(m_pSerializer, (StreamLabel)0); // 0 breaks recursion and represents the metadata event.

        SaveMetadataLabel(*instance.GetEvent(), metadataLabel);

        delete[] (pMetadataInstance->GetData());
        delete (pMetadataInstance);
    }

    // Write the event to the stream.
    instance.FastSerialize(m_pSerializer, metadataLabel);
}

StreamLabel EventPipeFile::GetMetadataLabel(EventPipeEvent &event)
{
    CONTRACTL
    {
        NOTHROW;
        GC_NOTRIGGER;
        MODE_ANY;
    }
    CONTRACTL_END;

    StreamLabel outLabel;
    if(m_pMetadataLabels->Lookup(&event, &outLabel))
    {
        _ASSERTE(outLabel != 0);
        return outLabel;
    }

    return 0;
}

void EventPipeFile::SaveMetadataLabel(EventPipeEvent &event, StreamLabel label)
{
    CONTRACTL
    {
        THROWS;
        GC_NOTRIGGER;
        MODE_ANY;
        PRECONDITION(label > 0);
    }
    CONTRACTL_END;

    // If a pre-existing metadata label exists, remove it.
    StreamLabel outLabel;
    if(m_pMetadataLabels->Lookup(&event, &outLabel))
    {
        m_pMetadataLabels->Remove(&event);
    }

    // Add the metadata label.
    m_pMetadataLabels->Add(&event, label);
}

#endif // FEATURE_PERFTRACING
