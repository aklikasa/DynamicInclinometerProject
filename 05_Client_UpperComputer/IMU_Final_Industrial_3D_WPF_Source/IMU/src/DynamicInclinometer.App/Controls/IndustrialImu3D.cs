using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Media.Media3D;

namespace DynamicInclinometer.App.Controls;

/// <summary>
/// Procedural, purely WPF/Direct3D 3D model of a generic sealed six-axis IMU.
/// Geometry is a visual proxy, not manufacturer CAD nor a dimensional calibration artifact.
/// Coordinate convention matches the existing application: body top +Z, length +X,
/// reference world axes stay fixed; only the DeviceVisual model receives the ESKF quaternion.
/// </summary>
internal static class IndustrialImu3D
{
    private const double BodyHalfX = 1.40;
    private const double BodyHalfY = .79;
    private const int CornerSteps = 7;

    private static Material Metal(Color diffuse, Color specular, double shininess=80)
    {
        var material=new MaterialGroup();
        material.Children.Add(new DiffuseMaterial(new SolidColorBrush(diffuse)));
        material.Children.Add(new SpecularMaterial(new SolidColorBrush(specular),shininess));
        return material;
    }
    private static void Attach(Model3DGroup target, MeshGeometry3D mesh, Material material)
        => target.Children.Add(new GeometryModel3D(mesh,material){BackMaterial=material});


    public static Model3DGroup CreateBody(QuaternionRotation3D sensorRotation, bool showAxes)
    {
        // A brand-neutral industrial tiltmeter enclosure, inspired by rugged CNC
        // aluminum instruments: top label, side cooling ribs, four mounting ears,
        // and a coaxial circular metal socket on the short (-X) end.
        // It is a VISUAL proxy: no dimensions, connector pinouts or mounting
        // distances should be used for actual mechanical design.
        var body = new Model3DGroup();

        // Base casting, body walls, lid gasket and stepped machined top.
        AddRoundedPrism(body,1.40,.79,.13,-.266,-.145,
            Metal(Color.FromRgb(107,115,118),Color.FromRgb(210,225,229),69));
        AddRoundedPrism(body,1.38,.77,.13,-.166,.151,
            Metal(Color.FromRgb(151,158,157),Color.FromRgb(235,238,234),88));
        AddRoundedPrism(body,1.414,.802,.145,.149,.180,
            Metal(Color.FromRgb(57,67,70),Color.FromRgb(129,147,155),58));
        AddRoundedPrism(body,1.42,.80,.15,.180,.246,
            Metal(Color.FromRgb(190,194,187),Color.FromRgb(255,253,245),99));
        AddRoundedPrism(body,1.325,.705,.13,.247,.263,
            Metal(Color.FromRgb(197,203,198),Color.FromRgb(248,251,247),102));

        // Four EXTERNAL mounting lugs, each with an actual void at its center.
        // The little bridges join the ring to the housing but do not fill its bore.
        for(int sx=-1;sx<=1;sx+=2)
        for(int sy=-1;sy<=1;sy+=2)
        {
            double hx=sx*1.53, hy=sy*.91;
            double bx0=sx>0?1.27:-1.52,bx1=sx>0?1.52:-1.27;
            double by0=sy>0?.68:-.87,by1=sy>0?.87:-.68;
            AddBox(body,bx0,bx1,by0,by1,-.263,-.174,
                Metal(Color.FromRgb(142,151,149),Color.FromRgb(225,230,221),78));
            AddVerticalRing(body,hx,hy,-.268,-.157,.212,.100,
                Metal(Color.FromRgb(180,185,178),Color.FromRgb(254,253,244),100));
            AddVerticalRing(body,hx,hy,-.157,-.146,.137,.101,
                Metal(Color.FromRgb(117,127,126),Color.FromRgb(235,236,227),80));
        }

        // Machined side ribs on the long faces of the aluminum body.
        for(int i=0;i<11;i++)
        {
            double x=-1.10+i*.219;
            AddRibOnSide(body,x,-.780,-.131,.118);
            AddRibOnSide(body,x, .780,-.131,.118);
        }

        // An M12-like *illustrative* round connector, NOT an electrical pinout.
        AddRoundConnector(body);

        // Recessed, logo-free dark nameplate with no maker or product trademark.
        AddRoundedPrism(body,.784,.393,.075,.265,.276,
            Metal(Color.FromRgb(39,52,60),Color.FromRgb(101,127,136),45));
        AddLabel(body);

        // Small unobtrusive status LED, not a lens that dominates the top cover.
        AddCylinder(body,1.09,-.48,.266,.054,.006,
            Metal(Color.FromRgb(34,40,43),Color.FromRgb(107,131,143),50));
        AddCylinder(body,1.09,-.48,.271,.028,.007,
            Metal(Color.FromRgb(43,145,200),Color.FromRgb(142,224,255),64));

        if(showAxes)
        {
            var origin=new Point3D(0,0,.31);
            AddArrow(body,origin,new Vector3D(1,0,0),1.62,
                Color.FromRgb(237,103,96));
            AddArrow(body,origin,new Vector3D(0,1,0),1.24,
                Color.FromRgb(92,212,149));
            AddArrow(body,origin,new Vector3D(0,0,1),1.17,
                Color.FromRgb(68,164,248));
        }

        // Only the complete body + its attached axis arrows follows the ESKF.
        body.Transform=new RotateTransform3D(sensorRotation);
        return body;
    }

    public static Model3DGroup CreateWorldReference(bool showAxes)
    {
        var world=new Model3DGroup();
        // Instrument dial remains in world frame. It never follows the IMU orientation.
        double z=-.58;
        AddAnnulus(world,2.00,.018,z,Color.FromRgb(43,115,171),Color.FromRgb(90,186,245));
        AddAnnulus(world,1.83,.008,z+.001,Color.FromRgb(36,69,89),Color.FromRgb(68,115,149));
        AddAnnulus(world,1.36,.007,z+.001,Color.FromRgb(38,69,86),Color.FromRgb(83,132,156));
        for(int degrees=0;degrees<360;degrees+=5)
        {
            double a=degrees*Math.PI/180;
            double inner=degrees%30==0?1.77:degrees%10==0?1.86:1.92;
            AddDialTick(world,a,inner,1.985,z+.006,
                degrees%30==0? .020:.010,
                degrees%30==0?Color.FromRgb(135,185,211):Color.FromRgb(60,113,146));
        }
        // Fixed world datum in the lower-left, visibly separate from the body axes.
        if(showAxes)
        {
            var o=new Point3D(-2.0,-1.57,-.54);
            AddArrow(world,o,new Vector3D(1,0,0),.46,Color.FromRgb(166,87,85));
            AddArrow(world,o,new Vector3D(0,1,0),.46,Color.FromRgb(70,151,104));
            AddArrow(world,o,new Vector3D(0,0,1),.46,Color.FromRgb(78,139,216));
        }
        return world;
    }

    private static Point3D[] Outline(double halfX,double halfY,double radius,double z)
    {
        var result=new List<Point3D>(4*(CornerSteps+1));
        // CCW rounded rectangle. Brisk planar face normals and smooth rounded corners.
        (double cx,double cy,double start)[] corners={
            (halfX-radius,-halfY+radius,-90), (halfX-radius,halfY-radius,0),
            (-halfX+radius,halfY-radius,90), (-halfX+radius,-halfY+radius,180)
        };
        foreach(var corner in corners)
        for(int i=0;i<=CornerSteps;i++)
        {
            double a=(corner.start+90.0*i/CornerSteps)*Math.PI/180;
            result.Add(new Point3D(corner.cx+radius*Math.Cos(a),corner.cy+radius*Math.Sin(a),z));
        }
        return result.ToArray();
    }

    private static void AddRoundedPrism(Model3DGroup target,double halfX,double halfY,double radius,
        double bottom,double top,Material material)
    {
        var mesh=new MeshGeometry3D();
        // Four horizontal profiles create two thin machined bevel transitions.
        var profiles=new[]{
            Outline(halfX-.037,halfY-.037,radius-.010,bottom),
            Outline(halfX,halfY,radius,bottom+.028),
            Outline(halfX,halfY,radius,top-.030),
            Outline(halfX-.040,halfY-.040,radius-.015,top)
        };
        int count=profiles[0].Length;
        for(int layer=0;layer<3;layer++)
        for(int i=0;i<count;i++)
        {
            int next=(i+1)%count;
            var a=profiles[layer][i];var b=profiles[layer][next];
            var c=profiles[layer+1][next];var d=profiles[layer+1][i];
            AddQuad(mesh,a,b,c,d);
        }
        AddFace(mesh,profiles[3],new Point3D(0,0,top),true);
        AddFace(mesh,profiles[0],new Point3D(0,0,bottom),false);
        Attach(target,mesh,material);
    }

    private static void AddFace(MeshGeometry3D mesh,Point3D[] perimeter,Point3D center,bool up)
    {
        for(int i=0;i<perimeter.Length;i++)
        {
            int j=(i+1)%perimeter.Length;
            if(up)AddTriangle(mesh,center,perimeter[i],perimeter[j]);
            else AddTriangle(mesh,center,perimeter[j],perimeter[i]);
        }
    }
    private static void AddQuad(MeshGeometry3D mesh,Point3D a,Point3D b,Point3D c,Point3D d)
    {AddTriangle(mesh,a,b,c);AddTriangle(mesh,a,c,d);}
    private static void AddTriangle(MeshGeometry3D mesh,Point3D a,Point3D b,Point3D c)
    {
        var n=Vector3D.CrossProduct(b-a,c-a);
        if(n.Length<1e-10)return;
        n.Normalize();int i=mesh.Positions.Count;
        mesh.Positions.Add(a);mesh.Positions.Add(b);mesh.Positions.Add(c);
        mesh.Normals.Add(n);mesh.Normals.Add(n);mesh.Normals.Add(n);
        mesh.TriangleIndices.Add(i);mesh.TriangleIndices.Add(i+1);mesh.TriangleIndices.Add(i+2);
    }

    private static void AddCylinder(Model3DGroup target,double x,double y,double z,double r,double height,Material material)
    {
        var mesh=new MeshGeometry3D();int sides=24;
        var bottom=new Point3D[sides];var top=new Point3D[sides];
        for(int i=0;i<sides;i++)
        {
            double theta=2*Math.PI*i/sides;
            bottom[i]=new Point3D(x+r*Math.Cos(theta),y+r*Math.Sin(theta),z);
            top[i]=new Point3D(bottom[i].X,bottom[i].Y,z+height);
        }
        for(int i=0;i<sides;i++)
        {
            int next=(i+1)%sides;
            AddQuad(mesh,bottom[i],bottom[next],top[next],top[i]);
            AddTriangle(mesh,new Point3D(x,y,z+height),top[i],top[next]);
            AddTriangle(mesh,new Point3D(x,y,z),bottom[next],bottom[i]);
        }
        Attach(target,mesh,material);
    }
    private static void AddTopRectangle(Model3DGroup target,double x,double y,double z,double dx,double dy,Color diffuse)
    {
        var mesh=new MeshGeometry3D();
        AddQuad(mesh,new Point3D(x-dx/2,y-dy/2,z),new Point3D(x+dx/2,y-dy/2,z),
            new Point3D(x+dx/2,y+dy/2,z),new Point3D(x-dx/2,y+dy/2,z));
        Attach(target,mesh,new DiffuseMaterial(new SolidColorBrush(diffuse)));
    }

    private static void AddBox(Model3DGroup target,double minX,double maxX,
        double minY,double maxY,double minZ,double maxZ,Material material)
    {
        var m=new MeshGeometry3D();
        var a=new Point3D(minX,minY,minZ);
        var b=new Point3D(maxX,minY,minZ);
        var c=new Point3D(maxX,maxY,minZ);
        var d=new Point3D(minX,maxY,minZ);
        var e=new Point3D(minX,minY,maxZ);
        var f=new Point3D(maxX,minY,maxZ);
        var g=new Point3D(maxX,maxY,maxZ);
        var h=new Point3D(minX,maxY,maxZ);
        AddQuad(m,a,b,c,d);AddQuad(m,e,h,g,f);
        AddQuad(m,a,e,f,b);AddQuad(m,b,f,g,c);
        AddQuad(m,c,g,h,d);AddQuad(m,d,h,e,a);
        Attach(target,m,material);
    }

    private static void AddVerticalRing(Model3DGroup target,double cx,double cy,
        double zBottom,double zTop,double outerRadius,double boreRadius,Material material)
    {
        var mesh=new MeshGeometry3D();const int sides=36;
        for(int i=0;i<sides;i++)
        {
            double a=2*Math.PI*i/sides,b=2*Math.PI*(i+1)/sides;
            Point3D At(double r,double z,double t)=>
                new Point3D(cx+r*Math.Cos(t),cy+r*Math.Sin(t),z);
            // Upper & lower annulus, outer shell, and open inner bore.
            AddQuad(mesh,At(boreRadius,zTop,a),At(outerRadius,zTop,a),
                At(outerRadius,zTop,b),At(boreRadius,zTop,b));
            AddQuad(mesh,At(boreRadius,zBottom,b),At(outerRadius,zBottom,b),
                At(outerRadius,zBottom,a),At(boreRadius,zBottom,a));
            AddQuad(mesh,At(outerRadius,zBottom,a),At(outerRadius,zBottom,b),
                At(outerRadius,zTop,b),At(outerRadius,zTop,a));
            AddQuad(mesh,At(boreRadius,zBottom,b),At(boreRadius,zBottom,a),
                At(boreRadius,zTop,a),At(boreRadius,zTop,b));
        }
        Attach(target,mesh,material);
    }

    private static void AddRibOnSide(Model3DGroup body,double x,double y,double bottom,double top)
    {
        // Grooves + narrow specular edge lines on the two long sides.
        // y is positioned at the physical side wall, not screen-space.
        double sign=Math.Sign(y),outside=y+sign*.014;
        var groove=new MeshGeometry3D();
        AddQuad(groove,new Point3D(x-.026,outside,bottom),
            new Point3D(x+.022,outside,bottom),new Point3D(x+.022,outside,top),
            new Point3D(x-.026,outside,top));
        Attach(body,groove,Metal(Color.FromRgb(98,107,108),Color.FromRgb(128,136,138),28));
        var edge=new MeshGeometry3D();
        double yy=outside+sign*.002;
        AddQuad(edge,new Point3D(x+.021,yy,bottom),new Point3D(x+.037,yy,bottom),
            new Point3D(x+.037,yy,top),new Point3D(x+.021,yy,top));
        Attach(body,edge,Metal(Color.FromRgb(195,202,199),Color.FromRgb(255,255,250),92));
    }

    private static void AddAxialCylinder(Model3DGroup target,
        double xStart,double xEnd,double centerY,double centerZ,
        double radius,Material material,int sides=36)
    {
        var mesh=new MeshGeometry3D();
        for(int i=0;i<sides;i++)
        {
            double a=2*Math.PI*i/sides,b=2*Math.PI*(i+1)/sides;
            Point3D At(double x,double angle)=>
                new Point3D(x,centerY+radius*Math.Cos(angle),centerZ+radius*Math.Sin(angle));
            AddQuad(mesh,At(xStart,a),At(xStart,b),At(xEnd,b),At(xEnd,a));
            AddTriangle(mesh,new Point3D(xStart,centerY,centerZ),
                At(xStart,b),At(xStart,a));
            AddTriangle(mesh,new Point3D(xEnd,centerY,centerZ),
                At(xEnd,a),At(xEnd,b));
        }
        Attach(target,mesh,material);
    }

    private static void AddRoundConnector(Model3DGroup body)
    {
        double cy=.0,cz=-.030;
        // It projects from the -X short end so the default three-quarter view
        // shows its metallic shell and actual recessed black mating socket.
        var nickel=Metal(Color.FromRgb(157,164,157),Color.FromRgb(251,249,240),106);
        var steel=Metal(Color.FromRgb(95,107,111),Color.FromRgb(235,241,238),82);
        AddAxialCylinder(body,-1.48,-1.36,cy,cz,.254,nickel);
        AddAxialCylinder(body,-1.71,-1.47,cy,cz,.265,nickel,12);
        AddAxialCylinder(body,-1.89,-1.71,cy,cz,.225,steel,36);
        AddAxialCylinder(body,-2.066,-1.88,cy,cz,.211,nickel,36);
        for(int i=0;i<5;i++)
        {
            double x=-1.91-i*.032;
            AddAxialCylinder(body,x-.007,x+.007,cy,cz,.225,
                Metal(Color.FromRgb(111,121,123),Color.FromRgb(232,241,238),78));
        }
        AddAxialCylinder(body,-2.113,-2.060,cy,cz,.230,nickel);
        AddAxialCylinder(body,-2.119,-2.105,cy,cz,.174,
            Metal(Color.FromRgb(16,22,25),Color.FromRgb(52,67,74),18));
        AddAxialCylinder(body,-2.124,-2.116,cy,cz,.146,
            Metal(Color.FromRgb(7,12,16),Color.FromRgb(18,25,31),10));
        // Five recessed socket contacts, purely cosmetic and not a pinout.
        var contacts=new[]{(-.073,-.062),(.072,-.062),(-.073,.061),(.071,.061),(.0,.0)};
        foreach(var (y,z) in contacts)
            AddAxialCylinder(body,-2.131,-2.121,cy+y,cz+z,.020,
                Metal(Color.FromRgb(130,141,144),Color.FromRgb(223,236,235),72),16);
    }

    private static void AddAnnulus(Model3DGroup target,double radius,double halfWidth,double z,Color diffuse,Color specular)
    {
        var mesh=new MeshGeometry3D();const int divisions=112;
        for(int i=0;i<divisions;i++)
        {
            double a=i*2*Math.PI/divisions,b=(i+1)*2*Math.PI/divisions;
            Point3D At(double r,double angle)=>new(r*Math.Cos(angle),r*Math.Sin(angle),z);
            AddQuad(mesh,At(radius-halfWidth,a),At(radius+halfWidth,a),
                At(radius+halfWidth,b),At(radius-halfWidth,b));
        }
        Attach(target,mesh,Metal(diffuse,specular,75));
    }
    private static void AddDialTick(Model3DGroup target,double angle,double from,double to,double z,double width,Color color)
    {
        var radial=new Vector3D(Math.Cos(angle),Math.Sin(angle),0);
        var side=new Vector3D(-Math.Sin(angle),Math.Cos(angle),0);
        Point3D At(double r,double w)=>new Point3D(0,0,z)+radial*r+side*w;
        var mesh=new MeshGeometry3D();
        AddQuad(mesh,At(from,-width/2),At(to,-width/2),At(to,width/2),At(from,width/2));
        Attach(target,mesh,new DiffuseMaterial(new SolidColorBrush(color)));
    }

    public static void AddArrow(Model3DGroup target,Point3D start,Vector3D direction,double length,Color color)
    {
        direction.Normalize();
        var helper=Math.Abs(direction.Z)<.95?new Vector3D(0,0,1):new Vector3D(0,1,0);
        var u=Vector3D.CrossProduct(helper,direction);u.Normalize();
        var v=Vector3D.CrossProduct(direction,u);v.Normalize();
        Point3D At(double axial,double r,double angle)=>start+direction*axial+u*(r*Math.Cos(angle))+v*(r*Math.Sin(angle));
        const int sides=14;const double radius=.026,headRadius=.117,headLength=.20;
        var mesh=new MeshGeometry3D();double stem=length-headLength;
        for(int i=0;i<sides;i++)
        {
            double a=2*Math.PI*i/sides,b=2*Math.PI*(i+1)/sides;
            AddQuad(mesh,At(0,radius,a),At(0,radius,b),At(stem,radius,b),At(stem,radius,a));
            AddTriangle(mesh,At(stem,headRadius,a),At(stem,headRadius,b),start+direction*length);
        }
        var mat=Metal(color,Color.FromRgb(225,232,239),55);
        Attach(target,mesh,mat);
    }


    private static void AddLabel(Model3DGroup body)
    {
        // Completely generic identifier. No brand name, logo or model number.
        var visual=new DrawingVisual();
        using(var context=visual.RenderOpen())
        {
            context.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(21,42,51)),
                new Pen(new SolidColorBrush(Color.FromRgb(109,137,145)),3),
                new Rect(4,4,724,352),25,25);
            context.DrawRectangle(new SolidColorBrush(Color.FromRgb(158,86,70)),
                null,new Rect(40,40,11,274));
            context.DrawText(new FormattedText("DYNAMIC INCLINOMETER",
                CultureInfo.GetCultureInfo("en-US"),FlowDirection.LeftToRight,
                new Typeface("Segoe UI Semibold"),45,
                new SolidColorBrush(Color.FromRgb(235,242,241)),1.0),new Point(78,66));
            context.DrawLine(new Pen(new SolidColorBrush(Color.FromRgb(93,128,137)),3),
                new Point(78,151),new Point(670,151));
            context.DrawText(new FormattedText("6-AXIS INERTIAL SENSOR",
                CultureInfo.GetCultureInfo("en-US"),FlowDirection.LeftToRight,
                new Typeface("Segoe UI"),32,
                new SolidColorBrush(Color.FromRgb(174,201,203)),1.0),new Point(80,186));
            context.DrawText(new FormattedText("ACC  +  GYRO    |    XYZ",
                CultureInfo.GetCultureInfo("en-US"),FlowDirection.LeftToRight,
                new Typeface("Consolas"),29,
                new SolidColorBrush(Color.FromRgb(150,177,180)),1.0),new Point(81,260));
        }
        var bitmap=new RenderTargetBitmap(732,360,96,96,PixelFormats.Pbgra32);
        bitmap.Render(visual);
        bitmap.Freeze();
        var texture=new ImageBrush(bitmap){Stretch=Stretch.Fill};
        texture.Freeze();
        var material=new MaterialGroup();
        material.Children.Add(new DiffuseMaterial(texture));
        material.Children.Add(new SpecularMaterial(
            new SolidColorBrush(Color.FromArgb(35,166,191,203)),48));
        var mesh=new MeshGeometry3D();
        var points=new[]{
            new Point3D(-.75,-.365,.279),new Point3D(.75,-.365,.279),
            new Point3D(.75,.365,.279),new Point3D(-.75,.365,.279)
        };
        foreach(var point in points)mesh.Positions.Add(point);
        mesh.TextureCoordinates.Add(new Point(0,1));
        mesh.TextureCoordinates.Add(new Point(1,1));
        mesh.TextureCoordinates.Add(new Point(1,0));
        mesh.TextureCoordinates.Add(new Point(0,0));
        foreach(int i in new[]{0,1,2,0,2,3})mesh.TriangleIndices.Add(i);
        for(int i=0;i<4;i++)mesh.Normals.Add(new Vector3D(0,0,1));
        Attach(body,mesh,material);
    }
}
