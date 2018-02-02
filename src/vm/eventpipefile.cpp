// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.
// See the LICENSE file in the project root for more information.

#include "common.h"
#include "eventpipebuffer.h"
#include "eventpipeblock.h"
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

    m_pBlock = new EventPipeBlock(100 * 1024);

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
    m_pMetadataIds = new MapSHashWithRemove<EventPipeEvent*, unsigned int>();

    m_metadataIdCounter = 0; // we start with 0, it's always gets incremented by generator so the first id will be 1, as specified in the docs

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

    if (m_pBlock != NULL && m_pSerializer != NULL)
    {
        WriteEnd();
    }

    if (m_pBlock != NULL)
    {
        delete(m_pBlock);
        m_pBlock = NULL;
    }

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

    // Check to see if we've seen this event type before.
    // If not, then write the event metadata to the event stream first.
    unsigned int metadataId = GetMetadataId(*instance.GetEvent());
    if(metadataId == 0)
    {
        metadataId = GenerateMetadataId();

        EventPipeEventInstance* pMetadataInstance = EventPipe::GetConfiguration()->BuildEventMetadataEvent(instance, metadataId);
        
        WriteToBlock(*pMetadataInstance, 0); // 0 breaks recursion and represents the metadata event.

        SaveMetadataId(*instance.GetEvent(), metadataId);

        delete[] (pMetadataInstance->GetData());
        delete (pMetadataInstance);
    }

    WriteToBlock(instance, metadataId);
}

void EventPipeFile::WriteEnd()
{
    CONTRACTL
    {
        NOTHROW;
        GC_NOTRIGGER;
        MODE_ANY;
    }
    CONTRACTL_END;

    m_pSerializer->WriteObject(m_pBlock); // we write current block to the disk, whether it's full or not

    m_pBlock->Clear();

    // "After the last EventBlock is emitted, the stream is ended by emitting a NullReference Tag which indicates that there are no more objects in the stream to read."
    // see https://github.com/Microsoft/perfview/blob/master/src/TraceEvent/EventPipe/EventPipeFormat.md for more
    m_pSerializer->WriteTag(FastSerializerTags::NullReference); 
}

void EventPipeFile::WriteToBlock(EventPipeEventInstance &instance, unsigned int metadataId)
{
    CONTRACTL
    {
        THROWS;
        GC_NOTRIGGER;
        MODE_ANY;
    }
    CONTRACTL_END;

    instance.SetMetadataId(metadataId);

    if (m_pBlock->WriteEvent(instance))
    {
        return; // the block is not full, we added the event and continue
    }

#ifdef _DEBUG
    if (m_lockOnWrite)
    {
        // Take the serialization lock.
        // This is used for synchronous file writes.
        // The circular buffer path only writes from one thread.
        SpinLockHolder _slh(&m_serializationLock);
    }
#endif // _DEBUG

    // we can't write this event to the current block (it's full)
    // so we write what we have in the block to the serializer
    m_pSerializer->WriteObject(m_pBlock);

    m_pBlock->Clear();

    bool result = m_pBlock->WriteEvent(instance);

    _ASSERTE(result == true); // we should never fail to add event to a clear block (if we do the max size is too small)
}

unsigned int EventPipeFile::GenerateMetadataId()
{
    CONTRACTL
    {
        NOTHROW;
        GC_NOTRIGGER;
        MODE_ANY;
    }
    CONTRACTL_END;

    return InterlockedIncrement(&m_metadataIdCounter);
}

unsigned int EventPipeFile::GetMetadataId(EventPipeEvent &event)
{
    CONTRACTL
    {
        NOTHROW;
        GC_NOTRIGGER;
        MODE_ANY;
    }
    CONTRACTL_END;

    unsigned int metadataId;
    if(m_pMetadataIds->Lookup(&event, &metadataId))
    {
        _ASSERTE(metadataId != 0);
        return metadataId;
    }

    return 0;
}

void EventPipeFile::SaveMetadataId(EventPipeEvent &event, unsigned int metadataId)
{
    CONTRACTL
    {
        THROWS;
        GC_NOTRIGGER;
        MODE_ANY;
        PRECONDITION(metadataId > 0);
    }
    CONTRACTL_END;

    // If a pre-existing metadata label exists, remove it.
    unsigned int oldId;
    if(m_pMetadataIds->Lookup(&event, &oldId))
    {
        m_pMetadataIds->Remove(&event);
    }

    // Add the metadata label.
    m_pMetadataIds->Add(&event, metadataId);
}

#endif // FEATURE_PERFTRACING
