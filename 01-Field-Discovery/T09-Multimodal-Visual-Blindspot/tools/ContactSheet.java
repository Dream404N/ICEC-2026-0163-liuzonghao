import java.awt.*;
import java.awt.image.*;
import java.io.*;
import java.util.*;
import javax.imageio.*;
import javax.imageio.stream.*;

/**
 * 生成带编号的 18 图联系表（contact sheet），用于人工复核真值标注。
 * 零第三方依赖，JDK 11+ 单文件源码启动。
 *
 * 用法: java ContactSheet.java <缩略图目录> <输出jpg> <列数> <每格宽度> [full|lower-left]
 * lower-left 模式只放大每张图的左下区域，用于核对「左下角是否有蓝色指示牌」这类细粒度真值。
 * 输出 reports/contact_sheet.jpg 作为报告附录的素材总览。
 */
public class ContactSheet {
    public static void main(String[] args) throws Exception {
        File dir = new File(args[0]);
        File out = new File(args[1]);
        int cols = Integer.parseInt(args[2]);
        int cellW = Integer.parseInt(args[3]);
        String crop = args.length > 4 ? args[4] : "full";
        int cellH = cellW * 3 / 4;
        int label = 22;

        File[] files = dir.listFiles((d, n) -> n.toLowerCase(Locale.ROOT).endsWith(".jpg"));
        if (files == null || files.length == 0) { System.out.println("NO_IMAGE"); return; }
        Arrays.sort(files);
        int rows = (files.length + cols - 1) / cols;
        BufferedImage sheet = new BufferedImage(cols * cellW, rows * (cellH + label), BufferedImage.TYPE_INT_RGB);
        Graphics2D g = sheet.createGraphics();
        g.setColor(Color.WHITE);
        g.fillRect(0, 0, sheet.getWidth(), sheet.getHeight());
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
        g.setFont(new Font("SansSerif", Font.BOLD, 14));
        for (int i = 0; i < files.length; i++) {
            BufferedImage im = ImageIO.read(files[i]);
            if (im != null && crop.equals("lower-left")) {
                int cw = (int) (im.getWidth() * 0.55), ch = (int) (im.getHeight() * 0.55);
                im = im.getSubimage(0, im.getHeight() - ch, cw, ch);
            }
            int x = (i % cols) * cellW, y = (i / cols) * (cellH + label);
            if (im != null) g.drawImage(im, x, y, cellW, cellH, null);
            g.setColor(new Color(31, 35, 40));
            String name = files[i].getName();
            String id = name.replaceAll(".*_(\\d+)_\\d+\\.jpg", "$1");
            g.drawString("#" + id + "  " + name, x + 4, y + cellH + 16);
            g.setColor(new Color(216, 222, 228));
            g.drawRect(x, y, cellW - 1, cellH - 1);
        }
        g.dispose();
        out.getParentFile().mkdirs();
        ImageWriter w = ImageIO.getImageWritersByFormatName("jpeg").next();
        ImageWriteParam p = w.getDefaultWriteParam();
        p.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
        p.setCompressionQuality(0.86f);
        try (ImageOutputStream ios = ImageIO.createImageOutputStream(out)) {
            w.setOutput(ios);
            w.write(null, new IIOImage(sheet, null, null), p);
        }
        w.dispose();
        System.out.println(out + " " + sheet.getWidth() + "x" + sheet.getHeight() + " " + files.length + " images");
    }
}
