// DXGI desktop-content probe: one duplication session for all explicit regions.
// LastPresentTime is an OS desktop update timestamp, never physical scanout.
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>
#include <cstdio>
#include <vector>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <array>
#include <string>
#include <sstream>
#include <cwctype>
using Microsoft::WRL::ComPtr;
static void check(HRESULT h,const char* name){if(FAILED(h)){char b[160];sprintf_s(b,"%s HRESULT=0x%08lx",name,h);throw std::runtime_error(b);}}
static double qpc(){LARGE_INTEGER t,f;QueryPerformanceCounter(&t);QueryPerformanceFrequency(&f);return double(t.QuadPart)/f.QuadPart;}
struct Row{double at,acquired,ms;unsigned accumulated;int code;unsigned long long hash;};
struct Probe {
    std::wstring name,file;int x,y,w,h,by,rx=0,ry=0,rw=0,rh=0;
    ComPtr<ID3D11Texture2D> staging;
    std::vector<Row> rows;
    std::vector<std::array<unsigned char,64*36*3>> features;
    Probe(std::wstring n,std::wstring f,int px,int py,int pw,int ph,int row):name(n),file(f),x(px),y(py),w(pw),h(ph),by(row){}
    void initialize(ID3D11Device* device,const RECT& desktop,double seconds){
        if(w<32||h<16||by>=1080||x<desktop.left||y<desktop.top||x+w>desktop.right||y+h>desktop.bottom)
            throw std::runtime_error("region outside the selected output or too small");
        rw=by>=0?w:std::min(640,w);rh=by>=0?5:std::min(240,h/2);
        rx=x-desktop.left+(by>=0?0:(w-rw)/2);
        ry=y-desktop.top+(by>=0?std::clamp(int(std::lround(h*by/1080.0))-2,0,h-5):(h-rh)/3);
        D3D11_TEXTURE2D_DESC td{};td.Width=rw;td.Height=rh;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        td.SampleDesc.Count=1;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        check(device->CreateTexture2D(&td,nullptr,&staging),"staging");rows.reserve(size_t(seconds*250));
        if(by<0)features.reserve(size_t(seconds*70));
    }
    void sample(ID3D11DeviceContext* context,ID3D11Texture2D* texture,const DXGI_OUTDUPL_FRAME_INFO& info,double frequency){
        if(rows.size()>=100000)throw std::runtime_error("bounded sample buffer exhausted");
        double begin=qpc();D3D11_BOX box{UINT(rx),UINT(ry),0,UINT(rx+rw),UINT(ry+rh),1};
        context->CopySubresourceRegion(staging.Get(),0,0,0,0,texture,0,&box);
        D3D11_MAPPED_SUBRESOURCE mapped;check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&mapped),"Map");
        int code=-1;unsigned long long hash=1469598103934665603ULL;
        if(by>=0){
            int bits[16]{};
            for(int i=0;i<16;i++){
                int px=int(std::lround((128+64*i)/1920.0*w));unsigned sum=0;
                for(int yy=1;yy<4;yy++)for(int xx=px-1;xx<=px+1;xx++){
                    auto b=static_cast<unsigned char*>(mapped.pData)+yy*mapped.RowPitch+xx*4;sum+=b[0]+b[1]+b[2];
                }bits[i]=sum>150*27;
            }
            if(bits[12]==0&&bits[13]==1&&bits[14]==0&&bits[15]==1){code=0;for(int i=0;i<12;i++)code|=bits[i]<<i;}
        }
        for(int yy=0;yy<rh;yy+=4)for(int xx=0;xx<rw;xx+=4){
            auto b=static_cast<unsigned char*>(mapped.pData)+yy*mapped.RowPitch+xx*4;
            for(int k=0;k<3;k++){hash^=b[k];hash*=1099511628211ULL;}
        }
        if(by<0){
            if(features.size()>=20000){context->Unmap(staging.Get(),0);throw std::runtime_error("bounded feature buffer exhausted");}
            std::array<unsigned char,64*36*3> feature{};
            for(int fy=0;fy<36;fy++)for(int fx=0;fx<64;fx++){
                unsigned sums[3]{};int count=0;
                for(int yy=fy*rh/36;yy<(fy+1)*rh/36;yy++)for(int xx=fx*rw/64;xx<(fx+1)*rw/64;xx++){
                    auto b=static_cast<unsigned char*>(mapped.pData)+yy*mapped.RowPitch+xx*4;
                    for(int k=0;k<3;k++)sums[k]+=b[2-k];count++;
                }
                for(int k=0;k<3;k++)feature[(fy*64+fx)*3+k]=static_cast<unsigned char>((sums[k]+count/2)/std::max(1,count));
            }features.push_back(feature);
        }
        context->Unmap(staging.Get(),0);double now=qpc();
        rows.push_back({double(info.LastPresentTime.QuadPart)/frequency,now,(now-begin)*1000,info.AccumulatedFrames,code,hash});
    }
    void ready(double at){
        FILE* f=nullptr;auto path=file+L".ready";
        if(_wfopen_s(&f,path.c_str(),L"wb")||!f)throw std::runtime_error("cannot write readiness");
        const auto& r=rows.front();
        fprintf(f,"{\"protocol\":3,\"ready_qpc_s\":%.9f,\"first_frame_qpc_s\":%.9f,\"first_frame_code\":%d,\"single_duplication\":true,\"viewport\":[%d,%d,%d,%d],\"crop\":[%d,%d,%d,%d]}\n",at,r.at,r.code,x,y,w,h,rx,ry,rw,rh);
        fclose(f);
    }
    void save(){
        FILE* f=nullptr;if(_wfopen_s(&f,file.c_str(),L"wb")||!f)throw std::runtime_error("cannot write output");
        fprintf(f,"desktop_qpc_s,acquired_qpc_s,copy_decode_ms,accumulated_frames,frame_code,roi_hash\n");
        for(auto&r:rows)fprintf(f,"%.9f,%.9f,%.6f,%u,%d,%llu\n",r.at,r.acquired,r.ms,r.accumulated,r.code,r.hash);
        fclose(f);
        if(by<0){auto path=file+L".rgb";if(_wfopen_s(&f,path.c_str(),L"wb")||!f)throw std::runtime_error("cannot write features");
            for(auto&feature:features)fwrite(feature.data(),1,feature.size(),f);fclose(f);}
    }
};
static std::vector<std::wstring> split(const std::wstring& value,wchar_t separator){
    std::wistringstream stream(value);std::wstring part;std::vector<std::wstring> parts;
    while(std::getline(stream,part,separator))parts.push_back(part);return parts;
}
int wmain(int argc,wchar_t** argv){
    if(argc==2&&std::wstring(argv[1])==L"--capabilities"){
        puts("{\"protocol\":3,\"multi_region\":true,\"ready_after_first_frame\":true}");return 0;
    }
    if(argc!=8){fprintf(stderr,"x y width height seconds barcode_y_normalized output.csv\n");return 2;}
    try{
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        int x=_wtoi(argv[1]),y=_wtoi(argv[2]),w=_wtoi(argv[3]),h=_wtoi(argv[4]);double seconds=_wtof(argv[5]);int by=_wtoi(argv[6]);
        if(w<32||h<16||!std::isfinite(seconds)||seconds<=0||seconds>300)throw std::runtime_error("invalid bounded viewport/duration");
        std::vector<Probe> probes;probes.emplace_back(L"primary",argv[7],x,y,w,h,by);
        wchar_t regions[4096]{};auto length=GetEnvironmentVariableW(L"TWOBYTEASR_CAPTURE_REGIONS",regions,4096);
        if(length>=4096)throw std::runtime_error("region description too long");
        std::wstring parent=argv[7];auto slash=parent.find_last_of(L"/\\");parent=slash==std::wstring::npos?L"":parent.substr(0,slash+1);
        if(length)for(auto& region:split(regions,L';')){
            auto fields=split(region,L',');if(fields.size()!=6||probes.size()>=5)throw std::runtime_error("at most four name,x,y,w,h,row regions");
            const auto& name=fields[0];
            if(name.empty()||name.size()>40||name==L"primary")throw std::runtime_error("invalid region name");
            for(auto c:name)if(!(iswalnum(c)||c==L'_'||c==L'-'))throw std::runtime_error("unsafe region name");
            for(auto& p:probes)if(p.name==name)throw std::runtime_error("duplicate region name");
            double fx=std::stod(fields[1]),fy=std::stod(fields[2]),fw=std::stod(fields[3]),fh=std::stod(fields[4]);
            if(!(fx>=0&&fy>=0&&fw>0&&fh>0&&fx+fw<=1&&fy+fh<=1))throw std::runtime_error("region must be inside the viewport");
            probes.emplace_back(name,parent+name+L"-desktop.csv",x+int(std::lround(fx*w)),y+int(std::lround(fy*h)),int(std::lround(fw*w)),int(std::lround(fh*h)),std::stoi(fields[5]));
        }
        ComPtr<IDXGIFactory1> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"factory");
        ComPtr<IDXGIAdapter1> adapter,chosen;ComPtr<IDXGIOutput> output;DXGI_OUTPUT_DESC desc{};
        for(UINT ai=0;factory->EnumAdapters1(ai,&adapter)!=DXGI_ERROR_NOT_FOUND;ai++){
            for(UINT oi=0;adapter->EnumOutputs(oi,&output)!=DXGI_ERROR_NOT_FOUND;oi++){
                output->GetDesc(&desc);auto r=desc.DesktopCoordinates;
                if(x>=r.left&&y>=r.top&&x+w<=r.right&&y+h<=r.bottom){chosen=adapter;break;}output.Reset();
            }if(chosen)break;adapter.Reset();
        }
        if(!chosen||!output)throw std::runtime_error("viewport must fit entirely on one attached output");
        ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;
        check(D3D11CreateDevice(chosen.Get(),D3D_DRIVER_TYPE_UNKNOWN,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,nullptr,&context),"D3D11CreateDevice");
        ComPtr<IDXGIOutput1> out1;check(output.As(&out1),"output1");ComPtr<IDXGIOutputDuplication> dup;
        check(out1->DuplicateOutput(device.Get(),&dup),"DuplicateOutput");
        for(auto& p:probes)p.initialize(device.Get(),desc.DesktopCoordinates,seconds);
        LARGE_INTEGER freq;QueryPerformanceFrequency(&freq);double end=qpc()+seconds;unsigned timeouts=0;bool ready=false;
        while(qpc()<end){
            DXGI_OUTDUPL_FRAME_INFO info{};ComPtr<IDXGIResource> resource;
            HRESULT hr=dup->AcquireNextFrame(100,&info,&resource);
            if(hr==DXGI_ERROR_WAIT_TIMEOUT){timeouts++;continue;}check(hr,"AcquireNextFrame");
            if(!info.LastPresentTime.QuadPart){dup->ReleaseFrame();continue;}
            ComPtr<ID3D11Texture2D> texture;check(resource.As(&texture),"texture");D3D11_TEXTURE2D_DESC actual;texture->GetDesc(&actual);
            if(actual.Format!=DXGI_FORMAT_B8G8R8A8_UNORM){dup->ReleaseFrame();throw std::runtime_error("unsupported desktop format; no silent HDR conversion");}
            for(auto& p:probes)p.sample(context.Get(),texture.Get(),info,double(freq.QuadPart));
            dup->ReleaseFrame();
            if(!ready){double at=qpc();for(auto& p:probes)p.ready(at);ready=true;}
        }
        for(auto& p:probes)p.save();
        fprintf(stderr,"protocol=3 single_duplication=true regions=%zu samples=%zu timeouts=%u monitor=%ls\n",probes.size(),probes.front().rows.size(),timeouts,desc.DeviceName);
        if(!ready)throw std::runtime_error("no desktop image acquired");return 0;
    }catch(const std::exception&e){fprintf(stderr,"%s\n",e.what());return 1;}
}
