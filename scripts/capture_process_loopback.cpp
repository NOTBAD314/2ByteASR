// Bounded, read-only WASAPI capture of one process tree. No device/session setters.
// Build with a Windows 10 SDK (20348+) and MSVC; output is stereo PCM16 WAV.
#define NOMINMAX
#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <wrl.h>
#include <cstdio>
#include <vector>
#include <cmath>
#include <algorithm>
using namespace Microsoft::WRL;
struct Handler : RuntimeClass<RuntimeClassFlags<ClassicCom>, IActivateAudioInterfaceCompletionHandler, FtmBase> {
    HANDLE done=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    HRESULT result=E_PENDING;
    ComPtr<IAudioClient> client;
    ~Handler(){CloseHandle(done);}
    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* op) override {
        ComPtr<IUnknown> unknown;
        HRESULT activated=E_FAIL;
        result=op->GetActivateResult(&activated,&unknown);
        if(SUCCEEDED(result))result=activated;
        if(SUCCEEDED(result))result=unknown.As(&client);
        SetEvent(done);return S_OK;
    }
};
static void require(HRESULT hr,const char* where){
    if(FAILED(hr)){std::fprintf(stderr,"%s HRESULT=0x%08lx\n",where,(unsigned long)hr);throw hr;}
}
int wmain(int argc,wchar_t** argv){
    if(argc!=4)return 2;
    DWORD pid=wcstoul(argv[1],nullptr,10);double seconds=wcstod(argv[2],nullptr);
    if(!pid||seconds<=0||seconds>30)return 2;
    CoInitializeEx(nullptr,COINIT_MULTITHREADED);
    try {
        AUDIOCLIENT_ACTIVATION_PARAMS params{};
        params.ActivationType=AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
        params.ProcessLoopbackParams.TargetProcessId=pid;
        params.ProcessLoopbackParams.ProcessLoopbackMode=PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
        PROPVARIANT prop{};prop.vt=VT_BLOB;
        prop.blob.cbSize=sizeof(params);prop.blob.pBlobData=reinterpret_cast<BYTE*>(&params);
        auto handler=Make<Handler>();ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
        require(ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,__uuidof(IAudioClient),&prop,handler.Get(),&operation),"activate");
        if(WaitForSingleObject(handler->done,10000)!=WAIT_OBJECT_0)return 3;
        require(handler->result,"activate-result");
        WAVEFORMATEX format{};format.wFormatTag=WAVE_FORMAT_PCM;format.nChannels=2;
        format.nSamplesPerSec=48000;format.wBitsPerSample=16;format.nBlockAlign=4;format.nAvgBytesPerSec=192000;
        auto client=handler->client;
        require(client->Initialize(AUDCLNT_SHAREMODE_SHARED,AUDCLNT_STREAMFLAGS_LOOPBACK|AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
            200000,0,&format,nullptr),"initialize");
        ComPtr<IAudioCaptureClient> capture;require(client->GetService(IID_PPV_ARGS(&capture)),"capture-service");
        std::vector<BYTE> data;
        require(client->Start(),"start");
        ULONGLONG end=GetTickCount64()+static_cast<ULONGLONG>(seconds*1000);
        while(GetTickCount64()<end){
            UINT32 available=0;require(capture->GetNextPacketSize(&available),"packet-size");
            while(available){
                BYTE* buffer=nullptr;UINT32 frames=0;DWORD flags=0;
                require(capture->GetBuffer(&buffer,&frames,&flags,nullptr,nullptr),"get-buffer");
                size_t count=frames*4;size_t old=data.size();data.resize(old+count,0);
                if(!(flags&AUDCLNT_BUFFERFLAGS_SILENT))std::copy(buffer,buffer+count,data.begin()+old);
                require(capture->ReleaseBuffer(frames),"release-buffer");
                require(capture->GetNextPacketSize(&available),"packet-size");
            }
            Sleep(5);
        }
        require(client->Stop(),"stop");
        FILE* file=nullptr;_wfopen_s(&file,argv[3],L"wb");if(!file)return 4;
        DWORD bytes=static_cast<DWORD>(data.size()),riff=bytes+36,fmtSize=16;
        fwrite("RIFF",1,4,file);fwrite(&riff,4,1,file);fwrite("WAVEfmt ",1,8,file);
        fwrite(&fmtSize,4,1,file);fwrite(&format,1,16,file);fwrite("data",1,4,file);fwrite(&bytes,4,1,file);
        fwrite(data.data(),1,data.size(),file);fclose(file);
        double energy=0;int peak=0;auto samples=reinterpret_cast<const short*>(data.data());
        for(size_t i=0;i<data.size()/2;i++){int v=samples[i];energy+=double(v)*v;peak=std::max(peak,std::abs(v));}
        std::printf("{\"target_pid\":%lu,\"frames\":%lu,\"rms\":%.9f,\"peak\":%.9f}\n",pid,bytes/4,
            bytes?std::sqrt(energy/(bytes/2))/32768.:0.,peak/32768.);
    }catch(HRESULT){return 1;}
    CoUninitialize();return 0;
}
