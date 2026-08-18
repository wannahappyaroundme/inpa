import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/kyungsbook/Desktop/inpa/outputs/019fc1be-edd6-7463-8802-d532951ee7a8";
const outputPath = `${outputDir}/인파_원수사_영업거점_80곳_우선40곳.xlsx`;
const checkedAt = "2026-08-03";

const sources = {
  kyobo: "https://www.kyobo.com/dgt/web/dtm/cs/ub/PCSUBNL7000",
  samsungFire: "https://www.samsungfire.com/sfmi/ui/m/home/cust/MO_CS_SearchBranchList.html",
  db: "https://www.idbins.com/FWCUSP1331.do",
};

const baseAction = "지점 대표번호로 지점장·팀장 연결 요청 → 15분 시연·사용성 인터뷰 일정 확정";
const clusterAction = "같은 건물의 지점별 관리직 미팅을 30분 간격으로 사전 확정 → 손글씨 엽서·리플렛·명함·스티커 전달";
const nationalAction = "같은 권역 2곳 이상 일정 확정 후 KTX·항공 이동 → 1명은 심층 인터뷰, 나머지는 15분 시연";

function target({ rank, phase, week, route, cluster, sector, company, channel, name, address, phone, manager = 5, planner = 5, certainty = 5, access, action, source }) {
  return { rank, phase, week, route, cluster, sector, company, channel, name, address, phone, manager, planner, certainty, access, action, source };
}

const targets = [
  target({rank:1, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림테크노마트", sector:"생명", company:"교보생명", channel:"FP", name:"남서울FP", address:"서울 구로구 새말로 97 26층 남서울FP지점 (구로동, 신도림테크노마트)", phone:"02-851-2996", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:2, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림테크노마트", sector:"생명", company:"교보생명", channel:"FP", name:"금천FP", address:"서울 구로구 새말로 97 27층 교보생명 금천FP지점 (구로동, 신도림테크노마트)", phone:"02-852-1765", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:3, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림테크노마트", sector:"생명", company:"교보생명", channel:"FP", name:"대방FP", address:"서울 구로구 새말로 97 26층 (구로동, 신도림테크노마트)", phone:"02-862-5653", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:4, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림테크노마트", sector:"생명", company:"교보생명", channel:"FP", name:"천일FP", address:"서울 구로구 새말로 97 27층 (구로동, 신도림테크노마트)", phone:"02-837-9758", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:5, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림테크노마트", sector:"생명", company:"교보생명", channel:"FP", name:"프라임FP", address:"서울 구로구 새말로 97 27층 (구로동, 신도림테크노마트)", phone:"02-869-0351", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:6, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림테크노마트", sector:"생명", company:"교보생명", channel:"FP", name:"한솔FP", address:"서울 구로구 새말로 97 27층 한솔FP지점 (구로동, 신도림테크노마트)", phone:"02-859-7943", access:5, action:clusterAction, source:sources.kyobo}),

  target({rank:7, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"신도림지점", address:"서울 구로구 경인로 662 29층 삼성화재 신도림지점 (신도림동, 디큐브시티)", phone:"02-320-7115", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:8, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"영등포지점", address:"서울 구로구 경인로 662 33층 영등포지점 (신도림동, 디큐브시티)", phone:"02-320-7230", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:9, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"신화지점", address:"서울 구로구 경인로 662 디큐브시티 오피스동 34층 삼성화재 신화지점 (신도림동)", phone:"02-330-3540", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:10, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"강서삼성지점", address:"서울 구로구 경인로 662 34층 강서삼성지점 (신도림동, 디큐브시티)", phone:"02-850-6151", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:11, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"노블레스서부지점", address:"서울 구로구 경인로 662 32층 노블레스서부지점 (신도림동, 디큐브시티)", phone:"02-330-3511", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:12, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"목동금융지점", address:"서울 구로구 경인로 662 35층 서부금융지점 (신도림동, 디큐브시티)", phone:"02-320-7021", manager:5, planner:4, access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:13, phase:"우선 40", week:"8/3-8/7", route:"구로·신도림", cluster:"신도림 디큐브시티", sector:"손해", company:"삼성화재", channel:"RC", name:"강서금융지점", address:"서울 구로구 경인로 662 35층 당산지점 (신도림동, 디큐브시티)", phone:"02-330-3737", manager:5, planner:4, access:5, action:clusterAction, source:sources.samsungFire}),

  target({rank:14, phase:"우선 40", week:"8/3-8/7", route:"구로디지털", cluster:"구로 G밸리", sector:"손해", company:"DB손해보험", channel:"PA", name:"개봉지점", address:"서울 구로구 디지털로 300 5층 (구로동, 지밸리비즈플라자)", phone:"02-860-0553", access:5, action:clusterAction, source:sources.db}),
  target({rank:15, phase:"우선 40", week:"8/3-8/7", route:"구로디지털", cluster:"구로 G밸리", sector:"손해", company:"DB손해보험", channel:"PA", name:"금천지점", address:"서울 구로구 디지털로 300 5층 (구로동, 지밸리비즈플라자)", phone:"02-860-0512", access:5, action:clusterAction, source:sources.db}),
  target({rank:16, phase:"우선 40", week:"8/3-8/7", route:"구로디지털", cluster:"구로 G밸리", sector:"손해", company:"DB손해보험", channel:"PA", name:"상도지점", address:"서울 구로구 디지털로 300 5층 (구로동, 지밸리비즈플라자)", phone:"02-860-0541", access:5, action:clusterAction, source:sources.db}),
  target({rank:17, phase:"우선 40", week:"8/3-8/7", route:"구로디지털", cluster:"구로 G밸리", sector:"손해", company:"DB손해보험", channel:"PA", name:"신길지점", address:"서울 구로구 디지털로 300 5층 (구로동, 지밸리비즈플라자)", phone:"02-860-0572", access:5, action:clusterAction, source:sources.db}),
  target({rank:18, phase:"우선 40", week:"8/3-8/7", route:"구로디지털", cluster:"구로 G밸리", sector:"손해", company:"DB손해보험", channel:"PA", name:"신대방지점", address:"서울 구로구 디지털로 306 206호 (구로동, 대륭포스트타워2차)", phone:"02-860-0564", access:5, action:clusterAction, source:sources.db}),

  target({rank:19, phase:"우선 40", week:"8/10-8/14", route:"영등포·당산", cluster:"교보생명 당산사옥", sector:"생명", company:"교보생명", channel:"FP", name:"영등포FP", address:"서울 영등포구 영등포로 96 2층 영등포FP지점 (당산동2가, 교보생명빌딩)", phone:"02-2672-5296", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:20, phase:"우선 40", week:"8/10-8/14", route:"영등포·당산", cluster:"교보생명 당산사옥", sector:"생명", company:"교보생명", channel:"FP", name:"여의도FP", address:"서울 영등포구 영등포로 96 3층 여의도FP지점 (당산동2가, 교보생명빌딩)", phone:"02-2631-5809", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:21, phase:"우선 40", week:"8/10-8/14", route:"영등포·당산", cluster:"교보생명 당산사옥", sector:"생명", company:"교보생명", channel:"FP", name:"당산FP", address:"서울 영등포구 영등포로 96 4층 당산FP지점 (당산동2가, 교보생명빌딩)", phone:"02-2671-5022", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:22, phase:"우선 40", week:"8/10-8/14", route:"영등포·당산", cluster:"교보생명 당산사옥", sector:"생명", company:"교보생명", channel:"FP", name:"대림FP", address:"서울 영등포구 영등포로 96 2층 대림FP지점 (당산동2가, 교보생명빌딩)", phone:"02-2634-5071", access:5, action:clusterAction, source:sources.kyobo}),
  target({rank:23, phase:"우선 40", week:"8/10-8/14", route:"영등포·당산", cluster:"교보생명 당산사옥", sector:"생명", company:"교보생명", channel:"FP", name:"양남FP", address:"서울 영등포구 영등포로 96 4층 양남FP지점 (당산동2가, 교보생명빌딩)", phone:"02-2634-8621", access:5, action:clusterAction, source:sources.kyobo}),

  target({rank:24, phase:"우선 40", week:"8/10-8/14", route:"문래", cluster:"문래 세미콜론", sector:"손해", company:"삼성화재", channel:"RC", name:"양천지점", address:"서울 영등포구 문래로28길 25 4층 양천지점 (문래동3가, 영시티N타워)", phone:"02-2654-4807", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:25, phase:"우선 40", week:"8/10-8/14", route:"문래", cluster:"문래 세미콜론", sector:"손해", company:"삼성화재", channel:"RC", name:"여의도지점", address:"서울 영등포구 문래로28길 25 4층 삼성화재 여의도지점 (문래동3가, 세미콜론문래)", phone:"02-857-2432", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:26, phase:"우선 40", week:"8/10-8/14", route:"문래", cluster:"문래 세미콜론", sector:"손해", company:"삼성화재", channel:"RC", name:"문래삼성지점", address:"서울 영등포구 문래로28길 25 5층 문래삼성지점 (문래동3가, 세미콜론문래N타워)", phone:"02-2636-2584", access:5, action:clusterAction, source:sources.samsungFire}),
  target({rank:27, phase:"우선 40", week:"8/10-8/14", route:"문래", cluster:"문래 세미콜론", sector:"손해", company:"삼성화재", channel:"RC", name:"문래SF지점", address:"서울 영등포구 문래로28길 25 8층 영등포SF지점 (문래동3가, 영시티N타워)", phone:"02-850-7950", access:5, action:clusterAction, source:sources.samsungFire}),

  target({rank:28, phase:"우선 40", week:"8/17-8/21", route:"강서·발산", cluster:"강서 송화쇼핑센터", sector:"생명", company:"교보생명", channel:"FP", name:"강서FP", address:"서울 강서구 강서로 267 7층 강서FP지점 (내발산동, 송화쇼핑센터)", phone:"02-2602-3741", access:4, action:clusterAction, source:sources.kyobo}),
  target({rank:29, phase:"우선 40", week:"8/17-8/21", route:"강서·발산", cluster:"강서 송화쇼핑센터", sector:"생명", company:"교보생명", channel:"FP", name:"마곡FP", address:"서울 강서구 강서로 267 7층 마곡FP지점 (내발산동, 송화쇼핑센터)", phone:"02-2696-6092", access:4, action:clusterAction, source:sources.kyobo}),
  target({rank:30, phase:"우선 40", week:"8/17-8/21", route:"강서·발산", cluster:"강서 송화쇼핑센터", sector:"생명", company:"교보생명", channel:"FP", name:"양천FP", address:"서울 강서구 강서로 267 6층 양천FP지점 (내발산동, 송화쇼핑센터)", phone:"02-2696-6141", access:4, action:clusterAction, source:sources.kyobo}),
  target({rank:31, phase:"우선 40", week:"8/17-8/21", route:"강서·발산", cluster:"강서 송화쇼핑센터", sector:"생명", company:"교보생명", channel:"FP", name:"방화FP", address:"서울 강서구 강서로 267 8층 방화FP지점 (내발산동, 송화쇼핑센터)", phone:"02-2664-7489", access:4, action:clusterAction, source:sources.kyobo}),

  target({rank:32, phase:"우선 40", week:"8/17-8/21", route:"마곡", cluster:"마곡 NY타워", sector:"손해", company:"DB손해보험", channel:"PA", name:"마곡지점", address:"서울 강서구 마곡동로3길 6 5층 (마곡동, NY타워)", phone:"02-2650-3833", manager:4, access:4, action:clusterAction, source:sources.db}),
  target({rank:33, phase:"우선 40", week:"8/17-8/21", route:"마곡", cluster:"마곡 NY타워", sector:"손해", company:"DB손해보험", channel:"PA", name:"양천지점", address:"서울 강서구 마곡동로3길 6 11층 (마곡동, NY타워)", phone:"02-2650-3830", manager:4, access:4, action:clusterAction, source:sources.db}),
  target({rank:34, phase:"우선 40", week:"8/17-8/21", route:"마곡", cluster:"마곡 NY타워", sector:"손해", company:"DB손해보험", channel:"PA", name:"화곡지점", address:"서울 강서구 마곡동로3길 6 6층 602호 (마곡동, NY타워)", phone:"02-2650-3880", manager:4, access:4, action:clusterAction, source:sources.db}),

  target({rank:35, phase:"우선 40", week:"8/17-8/21", route:"마곡", cluster:"마곡 마커스빌딩", sector:"손해", company:"삼성화재", channel:"RC", name:"강서혁신지점", address:"서울 강서구 마곡동로 55 4층 강서지점 (마곡동, 마커스빌딩)", phone:"02-2601-6449", manager:4, access:4, action:clusterAction, source:sources.samsungFire}),
  target({rank:36, phase:"우선 40", week:"8/17-8/21", route:"마곡", cluster:"마곡 마커스빌딩", sector:"손해", company:"삼성화재", channel:"RC", name:"마곡혁신지점", address:"서울 강서구 마곡동로 55 3층 (마곡동, 마커스빌딩)", phone:"02-2604-5049", manager:4, access:4, action:clusterAction, source:sources.samsungFire}),

  target({rank:37, phase:"우선 40", week:"8/24-8/28", route:"상암", cluster:"상암 성암로 179", sector:"손해", company:"삼성화재", channel:"RC", name:"마포지점", address:"서울 마포구 성암로 179 11층 마포지점 (상암동, 한샘상암)", phone:"02-317-5070", manager:4, access:4, action:clusterAction, source:sources.samsungFire}),
  target({rank:38, phase:"우선 40", week:"8/24-8/28", route:"상암", cluster:"상암 성암로 179", sector:"손해", company:"삼성화재", channel:"RC", name:"상암DMC지점", address:"서울 마포구 성암로 179 11층 서대문지점 (상암동)", phone:"02-317-5131", manager:4, access:4, action:clusterAction, source:sources.samsungFire}),
  target({rank:39, phase:"우선 40", week:"8/24-8/28", route:"합정", cluster:"합정오피스빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"서부지점", address:"서울 마포구 양화로 19 10층 (합정동, 합정오피스빌딩)", phone:"02-311-0114", manager:4, access:4, action:clusterAction, source:sources.db}),
  target({rank:40, phase:"우선 40", week:"8/24-8/28", route:"합정", cluster:"합정오피스빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"서대문지점", address:"서울 마포구 양화로 19 10층 (합정동, 합정오피스빌딩)", phone:"02-311-0117", manager:4, access:4, action:clusterAction, source:sources.db}),

  target({rank:41, phase:"확장 40", week:"9월 1주", route:"강남·서초", cluster:"교보타워 서초", sector:"생명", company:"교보생명", channel:"FP", name:"강남FP", address:"서울 서초구 강남대로 465 A동 4층 강남FP지점 (서초동, 교보타워)", phone:"02-3480-4561", access:3, action:baseAction, source:sources.kyobo}),
  target({rank:42, phase:"확장 40", week:"9월 1주", route:"강남·서초", cluster:"교보타워 서초", sector:"생명", company:"교보생명", channel:"FP", name:"강남VIPFP", address:"서울 서초구 강남대로 465 A동 5층 강남VIPFP지점 (서초동, 교보타워)", phone:"02-588-7459", access:3, action:baseAction, source:sources.kyobo}),
  target({rank:43, phase:"확장 40", week:"9월 1주", route:"강남·서초", cluster:"교보타워 서초", sector:"생명", company:"교보생명", channel:"FP", name:"강남타워FP", address:"서울 서초구 강남대로 465 A동 13층 강남타워FP지점 (서초동, 교보타워)", phone:"02-3480-4570", access:3, action:baseAction, source:sources.kyobo}),
  target({rank:44, phase:"확장 40", week:"9월 1주", route:"강남·서초", cluster:"국제전자센터", sector:"생명", company:"교보생명", channel:"FP", name:"도곡FP", address:"서울 서초구 효령로 304 17층 도곡FP지점 (서초동, 국제전자센터)", phone:"02-3481-2471", manager:4, access:3, action:baseAction, source:sources.kyobo}),
  target({rank:45, phase:"확장 40", week:"9월 1주", route:"강남·서초", cluster:"삼성화재 서초사옥", sector:"손해", company:"삼성화재", channel:"RC", name:"강남미래지점", address:"서울 서초구 강남대로 355 7층 YB1지점 (서초동, 삼성화재 서초사옥)", phone:"02-3465-8300", manager:4, access:3, action:baseAction, source:sources.samsungFire}),
  target({rank:46, phase:"확장 40", week:"9월 1주", route:"강남·서초", cluster:"삼성화재 역삼빌딩", sector:"손해", company:"삼성화재", channel:"RC", name:"강남중앙지점", address:"서울 강남구 테헤란로 114 19층 (역삼동, 역삼빌딩)", phone:"02-3468-9535", manager:4, access:3, action:baseAction, source:sources.samsungFire}),
  target({rank:47, phase:"확장 40", week:"9월 1주", route:"방배·사당", cluster:"방배 구산타워", sector:"손해", company:"삼성화재", channel:"RC", name:"방배지점", address:"서울 서초구 방배천로 91 15층 방배지점 (방배동, 구산타워)", phone:"02-585-7114", manager:4, access:3, action:baseAction, source:sources.samsungFire}),
  target({rank:48, phase:"확장 40", week:"9월 1주", route:"방배·사당", cluster:"방배 구산타워", sector:"손해", company:"삼성화재", channel:"RC", name:"서초지점", address:"서울 서초구 방배천로 91 16층 서초비전지점 (방배동, 구산타워)", phone:"02-521-9830", manager:4, access:3, action:baseAction, source:sources.samsungFire}),

  target({rank:49, phase:"확장 40", week:"9월 2주", route:"광명", cluster:"광명 대호엠스퀘어", sector:"생명", company:"교보생명", channel:"FP", name:"광명FP", address:"경기 광명시 신기로 21 10층 광명FP지점 (일직동, 대호엠스퀘어)", phone:"02-2682-3225", manager:4, access:4, action:baseAction, source:sources.kyobo}),
  target({rank:50, phase:"확장 40", week:"9월 2주", route:"광명", cluster:"광명 대호엠스퀘어", sector:"생명", company:"교보생명", channel:"FP", name:"광명제일FP", address:"경기 광명시 신기로 21 9층 광명제일FP지점 (일직동, 대호엠스퀘어)", phone:"02-892-5827", manager:4, access:4, action:baseAction, source:sources.kyobo}),
  target({rank:51, phase:"확장 40", week:"9월 2주", route:"부천", cluster:"부천 상동", sector:"생명", company:"교보생명", channel:"FP", name:"중동FP", address:"경기 부천시 송내대로 66 7층 중동FP지점 (상동, 용운빌딩)", phone:"032-327-8811", manager:3, access:4, action:baseAction, source:sources.kyobo}),
  target({rank:52, phase:"확장 40", week:"9월 2주", route:"안양", cluster:"교보생명 안양사옥", sector:"생명", company:"교보생명", channel:"FP", name:"안양미래FP", address:"경기 안양시 만안구 안양로 331 4층 안양미래FP지점 (안양동)", phone:"031-448-2298", manager:3, access:3, action:baseAction, source:sources.kyobo}),
  target({rank:53, phase:"확장 40", week:"9월 2주", route:"인천", cluster:"인천 구월동", sector:"생명", company:"교보생명", channel:"FP", name:"인천미래FP", address:"인천 남동구 예술로140번길 35 6층 인천미래FP지점 (구월동, 위너스글로벌)", phone:"032-433-0548", manager:3, access:2, action:baseAction, source:sources.kyobo}),
  target({rank:54, phase:"확장 40", week:"9월 2주", route:"부천", cluster:"부천 한화생명빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"부천지점", address:"경기 부천시 원미구 신흥로 179 14층 부천지점 (중동, 한화생명빌딩)", phone:"032-222-5738", manager:4, access:4, action:baseAction, source:sources.db}),
  target({rank:55, phase:"확장 40", week:"9월 2주", route:"부천", cluster:"부천 한화생명빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"신중동지점", address:"경기 부천시 원미구 신흥로 179 14층 신중동지점 (중동, 한화생명빌딩)", phone:"032-222-5722", manager:4, access:4, action:baseAction, source:sources.db}),
  target({rank:56, phase:"확장 40", week:"9월 2주", route:"안양", cluster:"DB손해보험 안양사옥", sector:"손해", company:"DB손해보험", channel:"PA", name:"안양지점", address:"경기 안양시 만안구 안양로 119 5층 DB손해보험 (안양동, 계양빌딩)", phone:"031-463-6120", manager:3, access:3, action:baseAction, source:sources.db}),

  target({rank:57, phase:"확장 40", week:"10월 1주", route:"대전·천안", cluster:"교보생명 대전사옥", sector:"생명", company:"교보생명", channel:"FP", name:"대전FP", address:"대전 중구 중앙로 69 6층 대전FP지점 (선화동, 교보생명빌딩)", phone:"042-229-5587", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:58, phase:"확장 40", week:"10월 1주", route:"대전·천안", cluster:"대전 오라클빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"대덕지점", address:"대전 서구 대덕대로 182 9층 (둔산동, 오라클빌딩)", phone:"042-600-7170", manager:4, access:1, action:nationalAction, source:sources.db}),
  target({rank:59, phase:"확장 40", week:"10월 1주", route:"대전·천안", cluster:"대전 오라클빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"둔산지점", address:"대전 서구 대덕대로 182 9층 (둔산동, 오라클빌딩)", phone:"042-600-7154", manager:4, access:1, action:nationalAction, source:sources.db}),
  target({rank:60, phase:"확장 40", week:"10월 1주", route:"대전·천안", cluster:"교보생명 천안사옥", sector:"생명", company:"교보생명", channel:"FP", name:"천안FP", address:"충남 천안시 동남구 충절로 138 3층 천안FP지점 (원성동)", phone:"041-564-6262", manager:3, access:1, action:nationalAction, source:sources.kyobo}),

  target({rank:61, phase:"확장 40", week:"10월 2주", route:"부산", cluster:"교보생명 부전동사옥", sector:"생명", company:"교보생명", channel:"FP", name:"경성FP", address:"부산 부산진구 중앙대로 658 3층 경성FP지점 (부전동, 교보생명빌딩)", phone:"051-811-7199", manager:4, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:62, phase:"확장 40", week:"10월 2주", route:"부산", cluster:"교보생명 부전동사옥", sector:"생명", company:"교보생명", channel:"FP", name:"남부산FP", address:"부산 부산진구 중앙대로 658 4층 남부산FP지점 (부전동, 교보생명빌딩)", phone:"051-811-7129", manager:4, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:63, phase:"확장 40", week:"10월 2주", route:"부산", cluster:"DB금융센터 부산", sector:"손해", company:"DB손해보험", channel:"PA", name:"부산중앙지점", address:"부산 부산진구 중앙대로 742 7층 부산중앙지점 (부전동, DB금융센터부산)", phone:"051-460-4810", manager:3, access:1, action:nationalAction, source:sources.db}),
  target({rank:64, phase:"확장 40", week:"10월 2주", route:"부산", cluster:"해운대 신세계프라자", sector:"손해", company:"DB손해보험", channel:"PA", name:"해운대지점", address:"부산 해운대구 해운대로 407 2층 (우동, 신세계프라자)", phone:"051-620-0772", manager:3, access:1, action:nationalAction, source:sources.db}),

  target({rank:65, phase:"확장 40", week:"10월 3주", route:"대구·포항", cluster:"교보생명 동성로사옥", sector:"생명", company:"교보생명", channel:"FP", name:"동성로FP", address:"대구 중구 국채보상로 586 6층 동성로FP지점 (동성로2가)", phone:"053-430-3690", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:66, phase:"확장 40", week:"10월 3주", route:"대구·포항", cluster:"KT대구지사", sector:"손해", company:"DB손해보험", channel:"PA", name:"대구지점", address:"대구 중구 동덕로 167 11층 (동인동2가, KT대구지사)", phone:"053-430-5210", manager:3, access:1, action:nationalAction, source:sources.db}),
  target({rank:67, phase:"확장 40", week:"10월 3주", route:"대구·포항", cluster:"교보생명 포항사옥", sector:"생명", company:"교보생명", channel:"FP", name:"대해FP", address:"경북 포항시 북구 중흥로 109 5층 대해FP지점 (죽도동, 교보생명빌딩)", phone:"054-271-6220", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:68, phase:"확장 40", week:"10월 3주", route:"대구·포항", cluster:"포항 산업은행빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"포항지점", address:"경북 포항시 북구 중흥로 156 3층 (죽도동, 산업은행빌딩)", phone:"054-271-4624", manager:3, access:1, action:nationalAction, source:sources.db}),

  target({rank:69, phase:"확장 40", week:"11월 1주", route:"광주·전주", cluster:"광주 디오빌", sector:"생명", company:"교보생명", channel:"FP", name:"광주중앙FP", address:"광주 서구 시청로 41 3층 광주중앙FP지점 (치평동, 디오빌)", phone:"062-513-6059", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:70, phase:"확장 40", week:"11월 1주", route:"광주·전주", cluster:"광주 오션5빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"광주서부지점", address:"광주 서구 상무중앙로 42 4층 광주서부지점 (치평동, 오션5빌딩)", phone:"062-370-7521", manager:3, access:1, action:nationalAction, source:sources.db}),
  target({rank:71, phase:"확장 40", week:"11월 1주", route:"광주·전주", cluster:"교보생명 전주사옥", sector:"생명", company:"교보생명", channel:"FP", name:"전주중앙FP", address:"전북 전주시 덕진구 기린대로 389 6층 전주중앙FP지점 (금암동, 교보생명빌딩)", phone:"063-259-5022", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:72, phase:"확장 40", week:"11월 1주", route:"광주·전주", cluster:"전주 대우빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"남전주지점", address:"전북 전주시 완산구 기린대로 213 11층 (서노송동, 대우빌딩)", phone:"063-230-4012", manager:3, access:1, action:nationalAction, source:sources.db}),

  target({rank:73, phase:"확장 40", week:"11월 2주", route:"울산·창원", cluster:"교보생명 울산사옥", sector:"생명", company:"교보생명", channel:"FP", name:"남울산FP", address:"울산 남구 중앙로 186 3층 남울산FP지점 (달동, 교보생명빌딩)", phone:"052-266-4438", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:74, phase:"확장 40", week:"11월 2주", route:"울산·창원", cluster:"울산 청보빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"울산지점", address:"울산 남구 번영로 122 6층 (달동, 청보빌딩)", phone:"052-228-4052", manager:3, access:1, action:nationalAction, source:sources.db}),
  target({rank:75, phase:"확장 40", week:"11월 2주", route:"울산·창원", cluster:"창원 교원공제회관", sector:"생명", company:"교보생명", channel:"FP", name:"창원FP", address:"경남 창원시 성산구 중앙대로 107 8층 창원FP지점 (중앙동, 교원공제회관)", phone:"055-282-1249", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:76, phase:"확장 40", week:"11월 2주", route:"울산·창원", cluster:"창원 STX빌딩", sector:"손해", company:"DB손해보험", channel:"PA", name:"성산지점", address:"경남 창원시 성산구 중앙대로 105 14층 (중앙동, STX빌딩)", phone:"055-280-8213", manager:3, access:1, action:nationalAction, source:sources.db}),

  target({rank:77, phase:"확장 40", week:"11월 3주", route:"강원·제주", cluster:"춘천 MK빌딩", sector:"생명", company:"교보생명", channel:"FP", name:"춘천FP", address:"강원 춘천시 방송길 98-1 5층 교보생명 춘천FP지점 (온의동, MK빌딩)", phone:"033-242-2245", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:78, phase:"확장 40", week:"11월 3주", route:"강원·제주", cluster:"원주 센트럴스퀘어", sector:"손해", company:"DB손해보험", channel:"PA", name:"원주지점", address:"강원 원주시 황금로 8 센트럴스퀘어 4층 DB손해보험 원주지점 (반곡동)", phone:"033-749-4020", manager:3, access:1, action:nationalAction, source:sources.db}),
  target({rank:79, phase:"확장 40", week:"11월 3주", route:"강원·제주", cluster:"교보생명 제주사옥", sector:"생명", company:"교보생명", channel:"FP", name:"탐라FP", address:"제주 제주시 전농로 118 7층 탐라FP지점 (이도일동, 교보빌딩)", phone:"064-751-0164", manager:3, access:1, action:nationalAction, source:sources.kyobo}),
  target({rank:80, phase:"확장 40", week:"11월 3주", route:"강원·제주", cluster:"제주 전문건설회관", sector:"손해", company:"DB손해보험", channel:"PA", name:"제주지점", address:"제주 제주시 연북로 17 4층 전문건설회관 DB손해보험 제주지점 (노형동)", phone:"064-710-5530", manager:3, access:1, action:nationalAction, source:sources.db}),
];

if (targets.length !== 80) throw new Error(`Expected 80 targets, got ${targets.length}`);

const topClusters = [
  [1, "8/3-8/7", "구로·신도림", "신도림테크노마트", "서울 구로구 새말로 97", "교보생명", "8/5 오전", "FP 6개 지점에 지점별 시간 확정, 2~3개 지점만 연속 방문"],
  [2, "8/3-8/7", "구로·신도림", "신도림 디큐브시티", "서울 구로구 경인로 662", "삼성화재", "8/6 오전", "RC 7개 지점, 대표번호 통화 후 지점장 미팅이 잡힌 곳만 방문"],
  [3, "8/3-8/7", "구로디지털", "구로 G밸리", "서울 구로구 디지털로 300·306", "DB손해보험", "8/7 오전", "PA 5개 지점, 가까운 회사 기반 첫 피드백 사용자 확보"],
  [4, "8/10-8/14", "영등포·당산", "교보생명 당산사옥", "서울 영등포구 영등포로 96", "교보생명", "8/12 오전", "FP 5개 지점, 오전 2곳·오후 1곳을 목표로 일정 분산"],
  [5, "8/10-8/14", "문래", "문래 세미콜론", "서울 영등포구 문래로28길 25", "삼성화재", "8/13 오전", "RC 4개 지점, 관리자 미팅 후 관심 설계사 1명 소개 요청"],
  [6, "8/17-8/21", "강서·발산", "강서 송화쇼핑센터", "서울 강서구 강서로 267", "교보생명", "8/19 오전", "FP 4개 지점, 설명보다 실제 증권 정리 시연을 중심으로 진행"],
  [7, "8/17-8/21", "마곡", "마곡 NY타워", "서울 강서구 마곡동로3길 6", "DB손해보험", "8/20 오전", "PA 3개 지점, 지점장 승인 뒤 경험 많은 설계사 연결 요청"],
  [8, "8/17-8/21", "마곡", "마곡 마커스빌딩", "서울 강서구 마곡동로 55", "삼성화재", "8/20 오후", "RC 2개 지점, 같은 날 NY타워 일정과 묶기"],
  [9, "8/24-8/28", "상암", "상암 성암로 179", "서울 마포구 성암로 179", "삼성화재", "8/26 오전", "RC 2개 지점, 8월 누적 반응을 반영한 시연으로 개선"],
  [10, "8/24-8/28", "합정", "합정오피스빌딩", "서울 마포구 양화로 19", "DB손해보험", "8/27 오전", "PA 2개 지점, 사용 시작자와 커피 심층 인터뷰 일정까지 확정"],
];

const wb = Workbook.create();
const dashboard = wb.worksheets.add("실행 요약");
const executeNow = wb.worksheets.add("바로 실행");
const monthly = wb.worksheets.add("월별 목표");
const priority = wb.worksheets.add("우선 40곳");
const all = wb.worksheets.add("전체 80곳");
const routes = wb.worksheets.add("건물별 동선");
const criteria = wb.worksheets.add("선정 기준·출처");

const navy = "#0F172A";
const teal = "#0F766E";
const lightTeal = "#CCFBF1";
const lightBlue = "#E0F2FE";
const lightAmber = "#FEF3C7";
const lightGreen = "#DCFCE7";
const lightGray = "#F1F5F9";
const border = "#CBD5E1";
const text = "#1E293B";
const white = "#FFFFFF";

for (const sheet of [dashboard, executeNow, monthly, priority, all, routes, criteria]) {
  sheet.showGridLines = false;
}

function titleBand(sheet, range, title, noteRange, note) {
  sheet.getRange(range).merge();
  sheet.getRange(range).values = [[title]];
  sheet.getRange(range).format = {
    fill: navy,
    font: { bold: true, color: white, size: 18 },
    verticalAlignment: "center",
    horizontalAlignment: "left",
  };
  sheet.getRange(range).format.rowHeight = 28;
  sheet.getRange(noteRange).merge();
  sheet.getRange(noteRange).values = [[note]];
  sheet.getRange(noteRange).format = {
    fill: lightBlue,
    font: { color: text, size: 10 },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange(noteRange).format.rowHeight = 32;
}

function headerStyle(range) {
  range.format = {
    fill: teal,
    font: { bold: true, color: white, size: 10 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
  range.format.rowHeight = 30;
}

// 전체 80곳
titleBand(all, "A1:Z2", "인파 원수사 영업거점 80곳", "A3:Z3", `구로 출발 기준, 공식 원수사 지점검색에서 ${checkedAt} 확인. 고객센터·보상센터·TM·GA센터는 제외하고 FP·RC·PA 현장 조직만 선정했습니다. 방문 전 지점장·팀장 일정 확인이 필요합니다.`);
const allHeaders = [["순위","단계","실행주차","권역","건물·클러스터","보험","회사","전속조직","대상지점","주소","전화","관리직 효과","설계사 접점","공식확인","구로 접근","효과점수","권장 접근","연락상태","미팅상태","관리직·팀","최근연락일","미팅일","사용시작자","피드백사용자","메모","공식출처"]];
all.getRange("A5:Z5").values = allHeaders;
headerStyle(all.getRange("A5:Z5"));
const allValues = targets.map(t => [t.rank,t.phase,t.week,t.route,t.cluster,t.sector,t.company,t.channel,t.name,t.address,t.phone,t.manager,t.planner,t.certainty,t.access,null,t.action,"미연락","미정","",null,null,0,0,"",t.source]);
all.getRange("A6:Z85").values = allValues;
all.getRange("P6").formulas = [["=ROUND((L6*30+M6*35+N6*20+O6*15)/5,0)"]];
all.getRange("P6:P85").fillDown();
all.getRange("A6:Z85").format = { font: { color: text, size: 9 }, verticalAlignment: "center" };
all.getRange("J6:J85").format.wrapText = true;
all.getRange("Q6:Q85").format.wrapText = true;
all.getRange("Y6:Z85").format.wrapText = true;
all.getRange("L6:P85").format.horizontalAlignment = "center";
all.getRange("A6:I85").format.verticalAlignment = "center";
all.getRange("R6:Y85").format.fill = lightAmber;
all.getRange("U6:V85").format.numberFormat = "yyyy-mm-dd";
all.getRange("W6:X85").format.numberFormat = "0";
all.getRange("R6:R85").dataValidation = { rule: { type: "list", values: ["미연락","1차연락","담당자연결","미팅제안","미팅확정","보류","거절"] } };
all.getRange("S6:S85").dataValidation = { rule: { type: "list", values: ["미정","일정확정","완료","재방문","종료"] } };
all.getRange("L6:O85").dataValidation = { rule: { type: "whole", operator: "between", formula1: 1, formula2: 5 } };
all.getRange("P6:P85").conditionalFormats.add("colorScale", { colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"], thresholds: ["min", {type:"percentile", value:50}, "max"] });
all.getRange("R6:R85").conditionalFormats.add("containsText", { text: "미팅확정", format: { fill: lightGreen, font: { bold: true, color: "#166534" } } });
all.getRange("S6:S85").conditionalFormats.add("containsText", { text: "완료", format: { fill: lightGreen, font: { bold: true, color: "#166534" } } });
all.getRange("X6:X85").conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { fill: lightGreen, font: { bold: true, color: "#166534" } } });
all.freezePanes.freezeRows(5);
all.freezePanes.freezeColumns(5);
all.tables.add("A5:Z85", true, "Target80Table").style = "TableStyleMedium2";
const allWidths = [55,72,92,90,150,55,90,65,125,360,105,62,62,62,62,70,300,85,85,105,88,88,70,78,220,270];
allWidths.forEach((w, i) => all.getRangeByIndexes(4, i, 81, 1).format.columnWidthPx = w);
all.getRange("A6:Z85").format.rowHeight = 38;

// 우선 40곳
titleBand(priority, "A1:L2", "8월 우선 대상 40곳", "A3:L3", "40개 지점을 10개 건물로 묶었습니다. 주소를 찾아가는 목록이 아니라, 전화로 관리직 미팅을 먼저 확정하는 대상 목록입니다. 전체 진행 기록은 ‘전체 80곳’에서 수정하세요.");
priority.getRange("A5:L5").values = [["순위","실행주차","권역","건물·클러스터","회사","조직","대상지점","전화","주소","효과점수","권장 접근","공식출처"]];
headerStyle(priority.getRange("A5:L5"));
const top40 = targets.slice(0, 40);
priority.getRange("A6:L45").values = top40.map((t) => [t.rank,t.week,t.route,t.cluster,t.company,t.channel,t.name,t.phone,t.address,null,t.action,t.source]);
for (let i = 0; i < 40; i++) priority.getRange(`J${6+i}`).formulas = [[`='전체 80곳'!P${6+i}`]];
priority.getRange("A6:L45").format = { font: { color: text, size: 9 }, verticalAlignment: "center" };
priority.getRange("I6:L45").format.wrapText = true;
priority.getRange("J6:J45").conditionalFormats.add("colorScale", { colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"], thresholds: ["min", {type:"percentile", value:50}, "max"] });
priority.freezePanes.freezeRows(5);
priority.freezePanes.freezeColumns(4);
priority.tables.add("A5:L45", true, "Priority40Table").style = "TableStyleMedium2";
[55,92,90,150,90,60,125,105,350,70,290,270].forEach((w, i) => priority.getRangeByIndexes(4, i, 41, 1).format.columnWidthPx = w);
priority.getRange("A6:L45").format.rowHeight = 38;

// 건물별 동선
titleBand(routes, "A1:I2", "8월 건물별 방문 동선", "A3:I3", "지점 수보다 ‘약속이 잡힌 관리직 수’를 우선합니다. 같은 건물에서 무리하게 전 지점을 돌지 말고, 하루 2~3개 미팅과 후속 연락 시간을 남깁니다.");
routes.getRange("A5:I5").values = [["순서","실행주차","권역","건물·클러스터","대표주소","대상수","회사","추천일","운영 방식"]];
headerStyle(routes.getRange("A5:I5"));
routes.getRange("A6:I15").values = topClusters.map(r => [...r.slice(0,5), null, ...r.slice(5)]);
for (let i = 0; i < topClusters.length; i++) routes.getRange(`F${6+i}`).formulas = [[`=COUNTIF('전체 80곳'!$E$6:$E$85,D${6+i})`]];
routes.getRange("A6:I15").format = { font: { color: text, size: 10 }, verticalAlignment: "center" };
routes.getRange("E6:E15").format.wrapText = true;
routes.getRange("I6:I15").format.wrapText = true;
routes.getRange("F6:F15").format = { fill: lightGreen, font: { bold: true, color: "#166534", size: 11 }, horizontalAlignment: "center" };
routes.tables.add("A5:I15", true, "RouteClustersTable").style = "TableStyleMedium2";
routes.freezePanes.freezeRows(5);
[55,95,90,165,260,65,100,90,360].forEach((w, i) => routes.getRangeByIndexes(4, i, 11, 1).format.columnWidthPx = w);
routes.getRange("A6:I15").format.rowHeight = 44;

// 날짜별 바로 실행
titleBand(executeNow, "A1:M2", "8월 날짜별 바로 실행", "A3:M3", "이 표의 숫자는 활동량이 아니라 완료 기준입니다. 주소로 바로 찾아가지 말고, 전화로 관리직 약속을 잡은 뒤 방문합니다. 사용 시작자는 가입이 아니라 실제 기능을 한 번 써본 사람으로 기록합니다.");
executeNow.getRange("A5:M5").values = [["날짜","요일","단계","정확한 대상","연락 목표","관리직 약속","현장 미팅","사용 시작","피드백","대표 역할","운영 역할","하루 완료 기준","상태"]];
headerStyle(executeNow.getRange("A5:M5"));
const dailyActions = [
  ["2026-08-03","월","1차 연락","1~18번: 신도림테크노마트 6, 디큐브시티 7, 구로 G밸리 5",18,4,0,0,0,"지점장·팀장 연결 요청, 15분 시연 목적 설명","통화 결과와 관리직 이름 기록, 미연결 지점 문자 후속","18곳 모두 담당자·재통화 시간·거절 중 하나로 분류","대기"],
  ["2026-08-04","화","약속 확정","1~18번 중 연결·재통화 대상",12,6,0,0,0,"미팅 시간 확정, 지점별 30분 간격 배치","시연 계정 점검, 손글씨 엽서와 인쇄물 세트 준비","8/5~8/7 관리직 약속 6건 이상 확정","대기"],
  ["2026-08-05","수","현장","1~6번: 신도림테크노마트 교보생명 FP",3,3,2,1,0,"관리직 15분 시연, 경험 있는 설계사 1명 소개 요청","차량 대기 중 미팅 기록, 감사 문자 초안 준비","미팅 2건, 실제 사용 시작 1명, 소개 1명","대기"],
  ["2026-08-06","목","현장","7~13번: 신도림 디큐브시티 삼성화재 RC",4,3,3,1,0,"관리직 시연, 첫 사용 날짜를 현장에서 확정","미팅별 반응·거절 이유 기록, 다음 약속 조정","미팅 3건, 실제 사용 시작 1명, 재접촉 1건","대기"],
  ["2026-08-07","금","현장·후속","14~18번: 구로 G밸리 DB손해보험 PA",5,2,2,1,1,"미팅과 첫 사용 확인, 다음 주 커피 인터뷰 제안","1~18번 전체 상태 정리, 다음 주 우선순위 재배치","주간 합계 미팅 6건 이상, 사용 3명, 피드백 1명","대기"],
  ["2026-08-10","월","사용 확인","1주차 사용 시작자와 소개받은 설계사",6,1,0,0,2,"사용 중 막힌 지점 10분 통화, 인터뷰 제안","질문·불편·요청을 기능별로 한 줄씩 기록","피드백 2명, 재방문 또는 커피 약속 1건","대기"],
  ["2026-08-11","화","1차 연락","19~27번: 당산 교보생명 FP 5, 문래 삼성화재 RC 4",9,4,0,0,0,"관리직 연결과 방문 시간 확정","9곳 통화 상태와 담당자 기록, 인쇄물 세트 준비","9곳 전부 분류, 관리직 약속 4건 이상","대기"],
  ["2026-08-12","수","현장","19~23번: 교보생명 당산사옥 FP",3,3,3,1,0,"관리직 3명 시연, 설계사 소개 2명 요청","현장 반응 기록, 감사 문자와 첫 사용 안내","미팅 3건, 사용 1명, 소개 2명","대기"],
  ["2026-08-13","목","현장","24~27번: 문래 세미콜론 삼성화재 RC",3,2,2,1,0,"관리직 2명 시연, 사용 시작 시간 약속","운영 질문 기록, 48시간 확인 일정 등록","미팅 2건, 사용 1명, 후속 일정 2건","대기"],
  ["2026-08-14","금","후속·인터뷰","1~27번 중 사용 시작자·관심 설계사",6,1,0,0,2,"커피 심층 인터뷰 1건, 소개 요청","누적 사용·피드백·거절 이유 정리","누적 사용 5명, 누적 피드백 3명 이상","대기"],
  ["2026-08-17","월","1차 연락","28~36번: 강서 교보생명 FP 4, 마곡 DB PA 3, 삼성화재 RC 2",9,4,0,0,0,"관리직 연결, 8/19~8/20 약속 확정","담당자 이름·시간 기록, 미연결 후속","9곳 전부 분류, 관리직 약속 4건 이상","대기"],
  ["2026-08-18","화","약속·사용 확인","28~36번 재통화, 기존 사용 시작자",8,4,0,0,1,"현장 약속 재확인, 기존 사용자 막힘 확인","시연 계정·동선·인쇄물 세트 점검","현장 약속 4건 유지, 피드백 1명 추가","대기"],
  ["2026-08-19","수","현장","28~31번: 강서 송화쇼핑센터 교보생명 FP",3,2,2,1,0,"실제 증권 정리 시연, 경험 설계사 소개 요청","미팅별 사용 시작일과 48시간 확인 일정 기록","미팅 2건, 사용 1명, 소개 1명","대기"],
  ["2026-08-20","목","현장","32~36번: 마곡 NY타워 DB PA, 마커스빌딩 삼성화재 RC",4,3,3,2,0,"오전 DB, 오후 삼성화재 시연과 첫 사용 확정","두 건물 이동 중 후속 문자, 반응 정리","미팅 3건, 사용 2명, 후속 일정 3건","대기"],
  ["2026-08-21","금","후속·인터뷰","1~36번 중 사용 시작자·관심 설계사",8,1,0,0,2,"커피 심층 인터뷰 1건, 소개 요청","사용자별 피드백을 문제·빈도·영향으로 기록","누적 사용 8명, 누적 피드백 6명 이상","대기"],
  ["2026-08-24","월","1차 연락·재접촉","37~40번 4곳과 이전 보류·관심 8곳",12,4,0,0,0,"상암·합정 약속 확정, 보류 대상 재제안","통화 결과 분류, 이번 주 인터뷰 대상 선정","관리직 약속 4건, 심층 인터뷰 2건 확정","대기"],
  ["2026-08-25","화","심층 인터뷰","기존 피드백 사용자 중 사용량 높은 2명",2,0,0,0,2,"커피 인터뷰 2건, 실제 사용 화면을 함께 확인","발언을 요약하지 말고 상황·행동·불편으로 기록","심층 인터뷰 2건, 개선 우선순위 3개 도출","대기"],
  ["2026-08-26","수","현장","37~38번: 상암 삼성화재 RC",2,2,2,1,0,"8월 개선 내용을 반영해 시연, 첫 사용 확정","현장 반응과 기존 시연 대비 차이 기록","미팅 2건, 사용 1명, 후속 일정 1건","대기"],
  ["2026-08-27","목","현장","39~40번: 합정 DB손해보험 PA",2,2,2,1,0,"관리직 시연, 첫 사용과 커피 인터뷰 일정 확정","감사 문자와 사용 확인 일정 등록","미팅 2건, 사용 1명, 인터뷰 약속 1건","대기"],
  ["2026-08-28","금","월 마감","우선 40곳 전체와 8월 사용 시작자",10,0,0,0,2,"보류·거절 사유 확인, 9월 소개 요청","40곳 상태 마감, 9월 41~56번 연락표 준비","40곳 100% 분류, 사용 10명, 피드백 8명 목표","대기"],
];
executeNow.getRange("A6:M25").values = dailyActions;
executeNow.getRange("A6:M25").format = { font:{color:text,size:9}, verticalAlignment:"center" };
executeNow.getRange("D6:D25").format.wrapText = true;
executeNow.getRange("J6:L25").format.wrapText = true;
executeNow.getRange("E6:I25").format.horizontalAlignment = "center";
executeNow.getRange("M6:M25").dataValidation = { rule:{type:"list",values:["대기","진행 중","완료","다음 날 이월"]} };
executeNow.getRange("M6:M25").format.fill = lightAmber;
executeNow.getRange("M6:M25").conditionalFormats.add("containsText", { text:"완료", format:{fill:lightGreen,font:{bold:true,color:"#166534"}} });
executeNow.tables.add("A5:M25", true, "AugustDailyExecutionTable").style = "TableStyleMedium2";
titleBand(monthly, "A1:H2", "연말 20명 달성 월별 기준", "A3:H3", "월별 완료 기준은 실제 기능 사용과 반복 피드백 여부입니다. 장거리 방문은 같은 권역에서 관리직 약속이 2건 이상 확정된 경우에만 진행합니다.");
monthly.getRange("A5:H5").values = [["월","신규 대상","관리직 미팅","신규 사용","누적 피드백 사용자","장거리 이동 조건","월말 완료 기준","판정"]];
headerStyle(monthly.getRange("A5:H5"));
monthly.getRange("A6:H10").values = [
  ["8월","1~40번 40곳",18,10,8,"서울 서부권 차량 운영","40곳 상태 100% 분류, 피드백 사용자 8명",""],
  ["9월","41~56번 16곳",8,4,12,"서울 강남·광명·부천·안양·인천","누적 피드백 사용자 12명",""],
  ["10월","57~68번 12곳",6,3,15,"한 권역 2곳 이상 약속 확정 시 이동","대전·부산·대구 권역 검증, 누적 15명",""],
  ["11월","69~80번 12곳",6,3,18,"한 권역 2곳 이상 약속 확정 시 이동","광주·전주·울산·창원·강원·제주 검증, 누적 18명",""],
  ["12월","기존 사용자와 소개 대상",6,2,20,"신규 장거리 방문보다 재방문 우선","실제 사용과 반복 피드백이 확인된 20명 확정",""],
];
monthly.getRange("A6:H10").format = { font:{color:text,size:10}, verticalAlignment:"center", wrapText:true };
monthly.getRange("C6:E10").format.horizontalAlignment = "center";
monthly.getRange("H6:H10").dataValidation = { rule:{type:"list",values:["미달","달성","초과달성"]} };
monthly.getRange("H6:H10").format.fill = lightAmber;
monthly.tables.add("A5:H10", true, "MonthlyTargetsTable").style = "TableStyleMedium2";
monthly.freezePanes.freezeRows(5);
[80,180,100,100,130,250,290,100].forEach((w, i) => monthly.getRangeByIndexes(4, i, 6, 1).format.columnWidthPx = w);
monthly.getRange("A6:H10").format.rowHeight = 56;
executeNow.freezePanes.freezeRows(5);
[95,55,95,300,70,80,75,75,70,260,280,300,90].forEach((w, i) => executeNow.getRangeByIndexes(4, i, 30, 1).format.columnWidthPx = w);
executeNow.getRange("A6:M25").format.rowHeight = 48;

// 선정 기준·출처
titleBand(criteria, "A1:F2", "선정 기준과 출처", "A3:F3", "공개된 공식 영업점 데이터가 명확한 교보생명 FP, 삼성화재 RC, DB손해보험 PA를 1차로 선정했습니다. 다른 원수사와 GA는 대표번호 연결 또는 공시명부 정리가 필요한 2차 조사 범위입니다.");
criteria.getRange("A5:D5").values = [["평가항목","가중치","5점 기준","선정 의미"]];
headerStyle(criteria.getRange("A5:D5"));
criteria.getRange("A6:D9").values = [
  ["설계사 접점",35,"전속 설계사가 상주하는 FP·RC·PA 지점","실제 사용 시작자와 반복 피드백 가능성"],
  ["관리직 효과",30,"같은 건물에 여러 지점·팀이 밀집","한 명의 조직 구매자가 아니라 초기 사용자 소개자 확보"],
  ["공식확인",20,"원수사 공식 지점검색의 최신 결과","고객센터·보상센터 혼입 방지"],
  ["구로 접근",15,"구로·신도림에서 차량 이동이 쉬움","8월 차량 운영 기간 내 반복 방문 가능성"],
];
criteria.getRange("A11:F11").values = [["구분","회사·기관","확인 내용","확인일","공식 URL","비고"]];
headerStyle(criteria.getRange("A11:F11"));
criteria.getRange("A12:F19").values = [
  ["영업점","교보생명","보험가입·계약상담 FP 지점 393개 검색 결과에서 선정",checkedAt,sources.kyobo,"FP·GFP·지원단 중 FP 현장지점 중심"],
  ["영업점","삼성화재","지역단·지점 검색 결과에서 RC 현장지점 선정",checkedAt,sources.samsungFire,"GA·TM·CS·보상·법인 조직 제외"],
  ["영업점","DB손해보험","보험가입상담 및 PA 창업 문의 영업지점 결과에서 선정",checkedAt,sources.db,"고객서비스센터·보상·정비망 제외"],
  ["회원사","생명보험협회","생명보험 정회원사와 본사 연락처 확인",checkedAt,"https://www.klia.or.kr/klia/company/member/list.do","다른 생명 원수사 2차 연결 근거"],
  ["회원사","손해보험협회","손해보험 정회원사 범위 확인",checkedAt,"https://kpub.knia.or.kr/managementDisc/spot/spotDisclosure.do","다른 손해 원수사 2차 연결 근거"],
  ["GA 2차","보험대리점공시","법인보험대리점 명부·공시 확인",checkedAt,"https://gapub.insure.or.kr/","원수사 1차 실행 후 대형 법인 GA부터 정리"],
  ["GA 2차","e클린보험서비스","보험설계사·대리점 등록정보 확인",checkedAt,"https://www.e-cleanins.or.kr/","개별 연락 전 소속·등록 상태 검증"],
  ["제외원칙","공통","고객PLAZA·보상센터·TM·GA센터·법인전담은 이번 80곳에서 제외",checkedAt,"-","개인 설계사 사용·피드백 목표에 맞춤"],
];
criteria.getRange("A21:F21").merge();
criteria.getRange("A21:F21").values = [["현장 적용 원칙"]];
criteria.getRange("A21:F21").format = { fill: teal, font: { bold: true, color: white, size: 11 }, verticalAlignment:"center" };
criteria.getRange("A22:F27").values = [
  ["1","전화 우선","지점장·팀장에게 15분 시연과 실제 사용성 피드백 요청","","",""],
  ["2","미팅 확정 후 방문","사전 승인 없이 인쇄물만 두고 오는 방식은 보조로만 사용","","",""],
  ["3","관리직 역할","팀 가입 결정권자가 아니라 본인 사용과 설계사 소개를 돕는 인플루언서","","",""],
  ["4","현장 목표","한 지점에서 관리직 1명 + 경험 있는 설계사 1명 소개","","",""],
  ["5","후속 목표","사용 시작 48시간 안에 첫 확인, 7일 안에 커피 심층 인터뷰 제안","","",""],
  ["6","최종 KPI","2026년 실제 피드백 사용자 20명 확보","","",""],
];
criteria.getRange("A6:F27").format = { font: { color: text, size: 10 }, verticalAlignment:"center" };
criteria.getRange("C6:F27").format.wrapText = true;
criteria.getRange("B6:B9").format.numberFormat = "0\"%\"";
[70,130,330,200,330,260].forEach((w, i) => criteria.getRangeByIndexes(4, i, 23, 1).format.columnWidthPx = w);
criteria.getRange("A6:F27").format.rowHeight = 44;
criteria.freezePanes.freezeRows(5);

// 실행 요약
titleBand(dashboard, "A1:H2", "인파 원수사 영업 실행 요약", "A3:H3", "목표: 실제 사용자가 인파를 써보고 지속적으로 피드백하는 상태 20명. 우선 40곳은 8월 서울 서부권, 확장 40곳은 9~11월 수도권·전국 권역입니다.");
const cards = [
  {label:"전체 후보", range:"A5:B5", valueRange:"A6:B7", formula:"=COUNTA('전체 80곳'!$I$6:$I$85)", fill:lightBlue},
  {label:"8월 우선", range:"C5:D5", valueRange:"C6:D7", formula:"=COUNTIF('전체 80곳'!$B$6:$B$85,\"우선 40\")", fill:lightTeal},
  {label:"연락 진행", range:"E5:F5", valueRange:"E6:F7", formula:"=COUNTA('전체 80곳'!$R$6:$R$85)-COUNTIF('전체 80곳'!$R$6:$R$85,\"미연락\")", fill:lightAmber},
  {label:"미팅 확정·완료", range:"G5:H5", valueRange:"G6:H7", formula:"=COUNTIF('전체 80곳'!$S$6:$S$85,\"일정확정\")+COUNTIF('전체 80곳'!$S$6:$S$85,\"완료\")+COUNTIF('전체 80곳'!$S$6:$S$85,\"재방문\")", fill:lightGreen},
  {label:"사용 시작자", range:"A9:B9", valueRange:"A10:B11", formula:"=SUM('전체 80곳'!$W$6:$W$85)", fill:lightBlue},
  {label:"피드백 사용자", range:"C9:D9", valueRange:"C10:D11", formula:"=SUM('전체 80곳'!$X$6:$X$85)", fill:lightGreen},
  {label:"2026 목표", range:"E9:F9", valueRange:"E10:F11", formula:"=20", fill:lightTeal},
  {label:"남은 인원", range:"G9:H9", valueRange:"G10:H11", formula:"=MAX(0,E10-C10)", fill:lightAmber},
];
for (const c of cards) {
  dashboard.getRange(c.range).merge();
  dashboard.getRange(c.range).values = [[c.label]];
  dashboard.getRange(c.range).format = { fill: navy, font: { bold:true, color:white, size:10 }, horizontalAlignment:"center", verticalAlignment:"center" };
  dashboard.getRange(c.valueRange).merge();
  dashboard.getRange(c.valueRange).formulas = [[c.formula]];
  dashboard.getRange(c.valueRange).format = { fill:c.fill, font:{bold:true,color:navy,size:22}, horizontalAlignment:"center", verticalAlignment:"center", borders:{preset:"outside",style:"thin",color:border} };
}
dashboard.getRange("A13:F13").merge();
dashboard.getRange("A13:F13").values = [["8월 실행 일정"]];
dashboard.getRange("A13:F13").format = { fill:teal, font:{bold:true,color:white,size:12}, verticalAlignment:"center" };
dashboard.getRange("A14:F14").values = [["주차","건물수","대상지점","핵심 권역","현장 목표","후속 목표"]];
headerStyle(dashboard.getRange("A14:F14"));
dashboard.getRange("A15:F18").values = [
  ["8/3-8/7",3,18,"구로·신도림","관리직 미팅 3~5건","사용 시작 2명"],
  ["8/10-8/14",2,9,"영등포·문래","관리직 미팅 3건","누적 사용 시작 5명"],
  ["8/17-8/21",3,9,"강서·마곡","관리직 미팅 3건","누적 피드백 5명"],
  ["8/24-8/28",2,4,"상암·합정","재방문·심층 인터뷰","8월 피드백 6명 이상"],
];
dashboard.getRange("A20:H20").merge();
dashboard.getRange("A20:H20").values = [["이번 주 착수 체크"]];
dashboard.getRange("A20:H20").format = { fill:teal, font:{bold:true,color:white,size:12}, verticalAlignment:"center" };
dashboard.getRange("A21:H25").values = [
  ["□","신도림테크노마트 FP 6곳에 전화","□","디큐브시티 RC 7곳에 전화","□","구로 G밸리 PA 5곳에 전화","담당","대표"],
  ["□","지점장·팀장 이름 기록","□","15분 미팅 목적 설명","□","약속 시간 30분 간격 배치","기한","8/4"],
  ["□","시연용 테스트 계정 점검","□","손글씨 엽서 준비","□","리플렛·명함·스티커 세트 준비","목표","미팅 3건"],
  ["□","미팅 후 당일 감사 문자","□","48시간 내 첫 사용 확인","□","7일 내 커피 인터뷰 제안","KPI","사용 2명"],
  ["□","거절 사유 한 줄 기록","□","소개받은 설계사 별도 등록","□","금요일에 다음 주 대상 재정렬","점검","8/7"],
];
dashboard.getRange("A14:F18").format = { font:{color:text,size:10}, verticalAlignment:"center" };
dashboard.getRange("A21:H25").format = { font:{color:text,size:10}, verticalAlignment:"center", wrapText:true, borders:{preset:"inside",style:"thin",color:border} };
dashboard.getRange("A21:H25").format.fill = lightGray;
dashboard.getRange("A14:F18").format.rowHeight = 30;
dashboard.getRange("A21:H25").format.rowHeight = 34;
[65,180,65,180,65,180,65,75].forEach((w, i) => dashboard.getRangeByIndexes(0, i, 26, 1).format.columnWidthPx = w);
dashboard.freezePanes.freezeRows(3);

await fs.mkdir(outputDir, { recursive: true });

const checks = {
  daily: await wb.inspect({ kind:"table", range:"바로 실행!A1:M12", include:"values,formulas", tableMaxRows:12, tableMaxCols:13, maxChars:14000 }),
  top: await wb.inspect({ kind:"table", range:"우선 40곳!A1:L12", include:"values,formulas", tableMaxRows:12, tableMaxCols:12, maxChars:12000 }),
  all: await wb.inspect({ kind:"table", range:"전체 80곳!A1:Z12", include:"values,formulas", tableMaxRows:12, tableMaxCols:26, maxChars:16000 }),
  route: await wb.inspect({ kind:"table", range:"건물별 동선!A1:I15", include:"values,formulas", tableMaxRows:15, tableMaxCols:9, maxChars:12000 }),
  errors: await wb.inspect({ kind:"match", searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options:{useRegex:true,maxResults:300}, summary:"final formula error scan" }),
};
console.log(checks.top.ndjson);
console.log(checks.daily.ndjson);
console.log(checks.route.ndjson);
console.log(checks.errors.ndjson);

for (const [sheetName, range, fileName] of [
  ["실행 요약","A1:H25","preview_dashboard.png"],
  ["바로 실행","A1:M15","preview_execute_now.png"],
  ["월별 목표","A1:H10","preview_monthly_targets.png"],
  ["우선 40곳","A1:L18","preview_priority.png"],
  ["전체 80곳","A1:Q16","preview_all.png"],
  ["건물별 동선","A1:I15","preview_routes.png"],
  ["선정 기준·출처","A1:F27","preview_criteria.png"],
]) {
  const preview = await wb.render({ sheetName, range, scale: 1, format:"png" });
  await fs.writeFile(`${outputDir}/${fileName}`, new Uint8Array(await preview.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);
console.log(`SAVED\t${outputPath}`);
